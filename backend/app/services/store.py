"""Tiny in-memory store for documents, quizzes and progress.

Good enough for the prototype. Everything is lost on restart; later you can
swap it for a JSON file or SQLite without touching the routers.
"""
from datetime import datetime, timezone

from app.schemas import DocumentInfo, QuizHistoryItem

documents: dict[str, DocumentInfo] = {}

# quiz_id -> {"quiz": QuizResponse, "answers": {question_id: (correct_answer, explanation)}}
quizzes: dict[str, dict] = {}

# user_id -> topic -> {"attempts": int, "correct": float, "last": datetime}
progress: dict[str, dict[str, dict]] = {}

# user_id -> list of QuizHistoryItem
history: dict[str, list[QuizHistoryItem]] = {}


def now() -> datetime:
    return datetime.now(timezone.utc)


def record_result(user_id: str, topic: str, score: float) -> None:
    t = progress.setdefault(user_id, {}).setdefault(topic, {"attempts": 0, "correct": 0.0, "last": None})
    t["attempts"] += 1
    t["correct"] += score
    t["last"] = now()


# exam_id -> {"exam": ExamResponse, "answers": {question_id: (correct_answer, explanation)}, "result": ExamResult | None}
exams: dict[str, dict] = {}

# user_id -> list of ExamHistoryItem (newest first)
exam_history: dict[str, list] = {}
