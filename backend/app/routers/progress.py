import uuid

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.prompts import templates
from app.routers.common import retrieve_or_404
from app.routers.quiz import generate_quiz
from app.schemas import PracticeRequest, PracticeResponse, PracticeTopic, ProgressResponse, QuizRequest, QuizResponse
from app.services import adaptive, mock, store
from app.services.llm import LLMClient, get_llm

router = APIRouter(prefix="/api", tags=["progress"])


@router.get("/progress/{user_id}", response_model=ProgressResponse, summary="Mastery per topic and quiz history")
async def get_progress(user_id: str):
    return ProgressResponse(
        user_id=user_id,
        topics=adaptive.topic_progress(user_id),
        weak_topics=adaptive.weak_topics(user_id),
        recent_quizzes=store.history.get(user_id, [])[:10],
    )


@router.post("/practice", response_model=PracticeResponse, summary="Adaptive practice on weak topics")
async def practice(req: PracticeRequest, llm: LLMClient = Depends(get_llm)):
    picked = adaptive.pick_practice_topics(req.user_id, req.max_topics)
    if picked:
        chosen = [(p.topic, p.mastery, f"Your mastery is {round(p.mastery * 100)}% after {p.attempts} questions.") for p in picked]
    else:
        # No history yet: start with the first topics of the uploaded documents.
        topics = [t for d in store.documents.values() for t in d.topics][: req.max_topics] or ["General review"]
        chosen = [(t, 0.5, "You haven't practised this yet.") for t in topics]

    selected = []
    for topic, m, reason in chosen:
        if get_settings().use_mocks:
            expl = mock.explanation(topic)
        else:
            _, context = retrieve_or_404(topic, req.document_ids, 5)
            expl = await llm.chat(templates.explain_prompt(topic, context))
        selected.append(PracticeTopic(topic=topic, mastery=m, reason=reason, explanation=expl))

    # One quiz per chosen topic, merged into a single quiz so each question keeps
    # its own topic (that's what progress is tracked by). Harder as mastery grows.
    questions, answers = [], {}
    for s in selected:
        difficulty = "easy" if s.mastery < 0.4 else "medium" if s.mastery < 0.75 else "hard"
        part = await generate_quiz(
            QuizRequest(topic=s.topic, difficulty=difficulty, num_mcq=req.questions_per_topic, num_short=0, document_ids=req.document_ids, user_id=req.user_id),
            llm,
        )
        questions += part.questions
        answers.update(store.quizzes.pop(part.quiz_id)["answers"])
    quiz = QuizResponse(quiz_id=f"quiz_{uuid.uuid4().hex[:8]}", topic="Adaptive practice", difficulty=questions[0].difficulty, questions=questions)
    store.quizzes[quiz.quiz_id] = {"quiz": quiz, "answers": answers}
    store.save()
    return PracticeResponse(user_id=req.user_id, selected=selected, quiz=quiz)
