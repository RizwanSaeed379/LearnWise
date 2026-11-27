from fastapi import APIRouter, Depends

from app.config import get_settings
from app.prompts import templates
from app.routers.common import retrieve_or_404
from app.schemas import AskRequest, AskResponse
from app.services import mock
from app.services.llm import LLMClient, get_llm
from app.services.verify import strip_bad_labels, verify_answer

router = APIRouter(prefix="/api", tags=["ask"])

NOT_FOUND = AskResponse(answer="I couldn't find this in your uploaded material.", sources=[], grounded=False)


@router.post("/ask", response_model=AskResponse, summary="Ask a question about your material (RAG)")
async def ask(req: AskRequest, llm: LLMClient = Depends(get_llm)):
    s = get_settings()
    if s.use_mocks:
        return AskResponse(answer=mock.answer(req.question), sources=mock.sources(2), grounded=True)

    sources, context = retrieve_or_404(req.question, req.document_ids, req.top_k)
    messages = templates.ask_prompt(req.question, context)
    text = await llm.chat(messages)
    if "NOT_FOUND" in text:
        return NOT_FOUND
    if not s.verify_answers:
        return AskResponse(answer=text, sources=sources, grounded=True)

    check = lambda t: verify_answer(t, sources, s.verify_sentence_support, s.verify_min_support)
    verdict = check(text)
    for _ in range(max(0, s.verify_retries)):
        if verdict.ok:
            break
        messages = messages + [{"role": "assistant", "content": text}, templates.ask_retry_message(verdict.problems(), len(sources))]
        retry = await llm.chat(messages)
        if "NOT_FOUND" in retry:
            return NOT_FOUND
        new = check(retry)
        if new.ok or (len(new.bad_labels), -new.support) < (len(verdict.bad_labels), -verdict.support):
            text, verdict = retry, new
    # Still unverified: keep the answer (it may be partly right) but flag it, and drop dead [S#] labels.
    return AskResponse(answer=strip_bad_labels(text, len(sources)), sources=sources, grounded=verdict.ok)
