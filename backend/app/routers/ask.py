import logging

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.prompts import templates
from app.routers.common import retrieve_or_404
from app.schemas import AskRequest, AskResponse
from app.services import followup, mock
from app.services.llm import LLMClient, LLMError, get_llm
from app.services.verify import strip_bad_labels, verify_answer

router = APIRouter(prefix="/api", tags=["ask"])
log = logging.getLogger("uvicorn.error")  # shows in the backend terminal next to the request lines

NOT_FOUND = AskResponse(answer="I couldn't find this in your uploaded material.", sources=[], grounded=False)


async def standalone_question(llm: LLMClient, question: str, history_text: str) -> str:
    """Rewrite a follow-up into a standalone question. Any failure keeps the original question."""
    try:
        text = await llm.chat(templates.rewrite_question_prompt(history_text, question), temperature=0.0, max_tokens=150)
    except LLMError as e:
        log.warning("ask follow-up: rewrite failed (%s)", e)
        return question
    cleaned = followup.clean_rewrite(text, question)
    log.info("ask follow-up: model rewrote %r as %r%s", question, text, "" if cleaned != question else " (not usable)")
    return cleaned


@router.post("/ask", response_model=AskResponse, summary="Ask a question about your material (RAG), with follow-up memory")
async def ask(req: AskRequest, llm: LLMClient = Depends(get_llm)):
    """Pipeline: [rewrite a follow-up] -> retrieve -> fenced context -> generate -> verify -> retry once -> flag.

    The history only helps understand the question; the answer is verified against the passages retrieved now."""
    s = get_settings()
    history = followup.trim_history(req.history, s.ask_history_turns, s.ask_history_chars)
    if s.use_mocks:
        search = f"{req.question} (about: {history[-1].question})" if followup.is_follow_up(req.question, history) else None
        return AskResponse(answer=mock.answer(search or req.question), search_query=search, sources=mock.sources(2), grounded=True)

    history_text = followup.history_block(history) if history else ""
    search, rewritten = req.question, None
    if followup.is_follow_up(req.question, history):
        rewritten = await standalone_question(llm, req.question, history_text)
        if rewritten.strip().lower() == req.question.strip().lower():
            # The model repeated the follow-up (or the rewrite failed), so it still can't be searched on its own:
            # search with the previous question in front. That text is for SEARCH only; the model is not told it
            # is the question, so it doesn't answer the previous question again.
            rewritten = None
            search = followup.fallback_query(req.question, history)
        else:
            search = rewritten
        log.info("ask follow-up: %r -> searched for %r", req.question, search)
    elif req.history:
        log.info("ask: %r (has %d earlier exchange(s); searched as asked)", req.question, len(history))
    search_query = search if search != req.question else None

    sources, context = retrieve_or_404(search, req.document_ids, req.top_k)
    messages = templates.ask_prompt(req.question, context, history_text, rewritten)
    text = await llm.chat(messages)
    if "NOT_FOUND" in text:
        return NOT_FOUND.model_copy(update={"search_query": search_query})
    if not s.verify_answers:
        return AskResponse(answer=text, search_query=search_query, sources=sources, grounded=True)

    check = lambda t: verify_answer(t, sources, s.verify_sentence_support, s.verify_min_support)
    verdict = check(text)
    for _ in range(max(0, s.verify_retries)):
        if verdict.ok:
            break
        messages = messages + [{"role": "assistant", "content": text}, templates.ask_retry_message(verdict.problems(), len(sources))]
        retry = await llm.chat(messages)
        if "NOT_FOUND" in retry:
            return NOT_FOUND.model_copy(update={"search_query": search_query})
        new = check(retry)
        if new.ok or (len(new.bad_labels), -new.support) < (len(verdict.bad_labels), -verdict.support):
            text, verdict = retry, new
    # Still unverified: keep the answer (it may be partly right) but flag it, and drop dead [S#] labels.
    return AskResponse(answer=strip_bad_labels(text, len(sources)), search_query=search_query, sources=sources, grounded=verdict.ok)
