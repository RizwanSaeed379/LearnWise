"""Graded mock exam: a personalised test (MCQ + short answers) that is marked and graded."""
import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.prompts import templates
from app.routers.quiz import make_questions
from app.schemas import (
    ExamHistory,
    ExamHistoryItem,
    ExamQuestion,
    ExamQuestionResult,
    ExamRequest,
    ExamResponse,
    ExamResult,
    ExamSubmitRequest,
)
from app.services import exam as ex
from app.services import mock, store
from app.services.llm import LLMClient, get_llm

router = APIRouter(prefix="/api/exam", tags=["exam"])


@router.post("", response_model=ExamResponse, status_code=201, summary="Generate a personalised, graded mock exam")
async def create_exam(req: ExamRequest, llm: LLMClient = Depends(get_llm)):
    if req.num_mcq + req.num_short == 0:
        raise HTTPException(400, detail="An exam needs at least one question.")
    plan = ex.build_plan(req.user_id, req.topics, req.document_ids, req.max_topics, req.num_mcq, req.num_short, req.difficulty)

    questions, keys = [], {}
    for p in plan:
        qs, k = await make_questions(p.topic, p.difficulty, p.num_mcq, p.num_short, req.document_ids, llm)
        for q in qs:
            questions.append(ExamQuestion(**q.model_dump(), marks=ex.MCQ_MARKS if q.type == "mcq" else ex.SHORT_MARKS))
        keys.update(k)
    # MCQs first, then short answers, like a paper exam.
    questions.sort(key=lambda q: q.type != "mcq")

    exam = ExamResponse(
        exam_id=f"exam_{uuid.uuid4().hex[:8]}",
        title=f"Mock exam: {', '.join(p.topic for p in plan)}",
        user_id=req.user_id,
        time_limit_minutes=req.time_limit_minutes,
        total_marks=sum(q.marks for q in questions),
        plan=plan,
        questions=questions,
        created_at=store.now(),
    )
    store.exams[exam.exam_id] = {"exam": exam, "answers": keys, "result": None}
    store.save()
    return exam


async def _mark_short(q: ExamQuestion, reference: str, explanation: str, answer: str, llm: LLMClient) -> tuple[float, str, list[str]]:
    """Returns (fraction 0-1, feedback, missing points)."""
    if not answer.strip():
        return 0.0, "No answer given. " + explanation, []
    if get_settings().use_mocks:
        frac = mock.grade_short(reference, answer)
        ref = [w.strip(".,").lower() for w in reference.split() if len(w) > 4]
        missing = [w for w in dict.fromkeys(ref) if w not in answer.lower()][:4]
        return frac, explanation, missing
    g = await llm.chat_json(templates.exam_grade_prompt(q.question, reference, answer, q.marks))
    try:
        frac = max(0.0, min(1.0, float(g.get("score", 0))))
    except (TypeError, ValueError):
        frac = 0.0
    missing = [str(m) for m in (g.get("missing_points") or []) if str(m).strip()][:5]
    return frac, str(g.get("feedback") or explanation), missing


@router.post("/{exam_id}/submit", response_model=ExamResult, summary="Submit the exam, get marks, grade and feedback")
async def submit_exam(exam_id: str, req: ExamSubmitRequest, llm: LLMClient = Depends(get_llm)):
    entry = store.exams.get(exam_id)
    if not entry:
        raise HTTPException(404, detail="Exam not found (exams are kept in memory until the server restarts).")
    if entry["result"] is not None:
        raise HTTPException(409, detail="This exam was already submitted. Fetch the result with GET /api/exam/{exam_id}/result.")
    exam: ExamResponse = entry["exam"]
    given = {a.question_id: a.answer for a in req.answers}

    shorts = [q for q in exam.questions if q.type == "short"]
    marked = await asyncio.gather(*(_mark_short(q, *entry["answers"][q.question_id], given.get(q.question_id, ""), llm) for q in shorts))
    short_marks = dict(zip((q.question_id for q in shorts), marked))

    results = []
    for q in exam.questions:
        correct_answer, explanation = entry["answers"][q.question_id]
        yours = given.get(q.question_id, "")
        if q.type == "mcq":
            frac = 1.0 if yours.strip() == correct_answer else 0.0
            awarded, missing, feedback = q.marks * frac, [], explanation
            shown_correct = q.options[int(correct_answer)]
            shown_yours = q.options[int(yours)] if yours.isdigit() and int(yours) < len(q.options) else yours
        else:
            frac, feedback, missing = short_marks[q.question_id]
            awarded = ex.round_half(frac * q.marks)
            shown_correct, shown_yours = correct_answer, yours
        store.record_result(req.user_id, q.topic, awarded / q.marks)
        results.append(ExamQuestionResult(
            question_id=q.question_id, type=q.type, question=q.question, topic=q.topic,
            marks_awarded=awarded, marks_available=q.marks, correct=awarded >= 0.6 * q.marks,
            your_answer=shown_yours, correct_answer=shown_correct, feedback=feedback, missing_points=missing,
        ))

    got = sum(r.marks_awarded for r in results)
    pct = round(100 * got / exam.total_marks, 1) if exam.total_marks else 0.0
    scores = ex.topic_scores(results)
    result = ExamResult(
        exam_id=exam_id, user_id=req.user_id, title=exam.title,
        marks_awarded=got, total_marks=exam.total_marks, percentage=pct,
        grade=ex.grade_for(pct), passed=pct >= ex.PASS_MARK,
        results=results, topic_scores=scores,
        strengths=[s.topic for s in scores if s.percentage >= 75],
        weak_topics=[s.topic for s in scores if s.percentage < 60],
        recommendations=ex.recommendations(scores, results),
        time_taken_seconds=req.time_taken_seconds,
        over_time=bool(req.time_taken_seconds and req.time_taken_seconds > exam.time_limit_minutes * 60),
        submitted_at=store.now(),
    )
    entry["result"] = result
    store.exam_history.setdefault(req.user_id, []).insert(0, ExamHistoryItem(
        exam_id=exam_id, title=exam.title, percentage=pct, grade=result.grade,
        marks_awarded=got, total_marks=exam.total_marks, taken_at=result.submitted_at,
    ))
    store.save()
    return result


@router.get("/{exam_id}/result", response_model=ExamResult, summary="The marked result of a submitted exam")
async def get_result(exam_id: str):
    entry = store.exams.get(exam_id)
    if not entry:
        raise HTTPException(404, detail="Exam not found.")
    if entry["result"] is None:
        raise HTTPException(404, detail="This exam has not been submitted yet.")
    return entry["result"]


@router.get("/history/{user_id}", response_model=ExamHistory, summary="Past exam grades for a student")
async def history(user_id: str):
    return ExamHistory(user_id=user_id, exams=store.exam_history.get(user_id, []))
