import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.prompts import templates
from app.routers.common import retrieve_or_404, source_for_label
from app.schemas import (
    QuestionResult,
    QuizHistoryItem,
    QuizQuestion,
    QuizRequest,
    QuizResponse,
    QuizSubmitRequest,
    QuizSubmitResponse,
)
from app.services import adaptive, mock, store
from app.services.llm import LLMClient, get_llm
from app.services.validation import clean_quiz_items

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


async def make_questions(topic: str, difficulty: str, num_mcq: int, num_short: int, document_ids, llm: LLMClient) -> tuple[list[QuizQuestion], dict[str, tuple[str, str]]]:
    """Generate validated questions for one topic. Returns (questions without answers, answer key)."""
    if get_settings().use_mocks:
        return mock.quiz_questions(topic, difficulty, num_mcq, num_short)
    sources, context = retrieve_or_404(topic, document_ids, 8)
    data = await llm.chat_json(templates.quiz_prompt(topic, difficulty, num_mcq, num_short, context), max_tokens=3000)
    questions, keys = [], {}
    for it in clean_quiz_items(data.get("questions", [])):
        qid = f"q_{uuid.uuid4().hex[:8]}"
        questions.append(QuizQuestion(question_id=qid, type=it["type"], question=it["question"], options=it["options"], topic=topic, difficulty=difficulty, source=source_for_label(it.get("source"), sources)))
        keys[qid] = (it["answer"], it["explanation"])
    if not questions:
        raise HTTPException(502, detail="The model did not produce valid questions. Try again.")
    return questions, keys


async def generate_quiz(req: QuizRequest, llm: LLMClient) -> QuizResponse:
    """Create a quiz, remember its answer key server-side, return it WITHOUT answers."""
    questions, keys = await make_questions(req.topic, req.difficulty, req.num_mcq, req.num_short, req.document_ids, llm)
    quiz = QuizResponse(quiz_id=f"quiz_{uuid.uuid4().hex[:8]}", topic=req.topic, difficulty=req.difficulty, questions=questions)
    store.quizzes[quiz.quiz_id] = {"quiz": quiz, "answers": keys}
    return quiz


@router.post("", response_model=QuizResponse, summary="Generate MCQ + short-answer questions")
async def create_quiz(req: QuizRequest, llm: LLMClient = Depends(get_llm)):
    return await generate_quiz(req, llm)


@router.post("/{quiz_id}/submit", response_model=QuizSubmitResponse, summary="Submit answers, get score and feedback")
async def submit_quiz(quiz_id: str, req: QuizSubmitRequest, llm: LLMClient = Depends(get_llm)):
    entry = store.quizzes.get(quiz_id)
    if not entry:
        raise HTTPException(404, detail="Quiz not found (quizzes are kept in memory until the server restarts).")
    quiz: QuizResponse = entry["quiz"]
    given = {a.question_id: a.answer for a in req.answers}

    results = []
    for q in quiz.questions:
        correct_answer, explanation = entry["answers"][q.question_id]
        yours = given.get(q.question_id, "")
        if q.type == "mcq":
            score = 1.0 if yours.strip() == correct_answer else 0.0
            shown_correct = q.options[int(correct_answer)]
            shown_yours = q.options[int(yours)] if yours.isdigit() and int(yours) < len(q.options) else yours
        else:
            if get_settings().use_mocks:
                score = mock.grade_short(correct_answer, yours)
            else:
                g = await llm.chat_json(templates.grade_short_prompt(q.question, correct_answer, yours))
                score = max(0.0, min(1.0, float(g.get("score", 0))))
                explanation = g.get("feedback") or explanation
            shown_correct, shown_yours = correct_answer, yours
        store.record_result(req.user_id, q.topic, score)
        results.append(QuestionResult(question_id=q.question_id, correct=score >= 0.6, score=score, your_answer=shown_yours, correct_answer=shown_correct, explanation=explanation, topic=q.topic))

    total = len(results)
    score = round(sum(r.score for r in results), 2)
    pct = round(100 * score / total, 1) if total else 0.0
    store.history.setdefault(req.user_id, []).insert(0, QuizHistoryItem(quiz_id=quiz_id, topic=quiz.topic, difficulty=quiz.difficulty, percentage=pct, taken_at=store.now()))
    return QuizSubmitResponse(quiz_id=quiz_id, score=score, total=total, percentage=pct, results=results, weak_topics=adaptive.weak_topics(req.user_id))
