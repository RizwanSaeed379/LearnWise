"""Storage for documents, quizzes, exams and progress.

The routers use these plain dicts. In real mode (USE_MOCKS=false) everything is
also saved to DATA_DIR/store.json after each change and loaded at startup, so a
restart doesn't lose your library, progress or exam history. Mock mode stays
in memory only.
"""
import json
import os
import threading
from datetime import datetime, timezone

from app.schemas import DocumentInfo, ExamHistoryItem, ExamResponse, ExamResult, QuizHistoryItem, QuizResponse

documents: dict[str, DocumentInfo] = {}

# quiz_id -> {"quiz": QuizResponse, "answers": {question_id: (correct_answer, explanation)}}
quizzes: dict[str, dict] = {}

# user_id -> topic -> {"attempts": int, "correct": float, "last": datetime}
progress: dict[str, dict[str, dict]] = {}

# user_id -> list of QuizHistoryItem
history: dict[str, list[QuizHistoryItem]] = {}

# exam_id -> {"exam": ExamResponse, "answers": {question_id: (correct_answer, explanation)}, "result": ExamResult | None}
exams: dict[str, dict] = {}

# user_id -> list of ExamHistoryItem (newest first)
exam_history: dict[str, list] = {}

_lock = threading.Lock()
_KEEP_QUIZZES = 200  # unsubmitted quizzes pile up; keep the newest


def now() -> datetime:
    return datetime.now(timezone.utc)


def record_result(user_id: str, topic: str, score: float) -> None:
    t = progress.setdefault(user_id, {}).setdefault(topic, {"attempts": 0, "correct": 0.0, "last": None})
    t["attempts"] += 1
    t["correct"] += score
    t["last"] = now()


# ---------------------------------------------------------------- persistence
def _path() -> str:
    from app.config import get_settings

    return os.path.join(get_settings().data_dir, "store.json")


def _enabled() -> bool:
    from app.config import get_settings

    return not get_settings().use_mocks


def _dump() -> dict:
    keys = list(quizzes)[-_KEEP_QUIZZES:]
    return {
        "version": 1,
        "documents": {k: v.model_dump(mode="json") for k, v in documents.items()},
        "quizzes": {k: {"quiz": quizzes[k]["quiz"].model_dump(mode="json"), "answers": quizzes[k]["answers"]} for k in keys},
        "progress": {u: {t: {**d, "last": d["last"].isoformat() if d["last"] else None} for t, d in ts.items()} for u, ts in progress.items()},
        "history": {u: [h.model_dump(mode="json") for h in hs] for u, hs in history.items()},
        "exams": {
            k: {"exam": e["exam"].model_dump(mode="json"), "answers": e["answers"], "result": e["result"].model_dump(mode="json") if e["result"] else None}
            for k, e in exams.items()
        },
        "exam_history": {u: [h.model_dump(mode="json") for h in hs] for u, hs in exam_history.items()},
    }


def save() -> None:
    """Write everything to DATA_DIR/store.json (atomic: write a temp file, then rename)."""
    if not _enabled():
        return
    with _lock:
        path = _path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_dump(), f, ensure_ascii=False)
        os.replace(tmp, path)


def load() -> None:
    """Load DATA_DIR/store.json if it exists (called once at startup in real mode)."""
    if not _enabled() or not os.path.exists(_path()):
        return
    with open(_path(), encoding="utf-8") as f:
        data = json.load(f)
    keys = lambda d: {q: tuple(v) for q, v in d.items()}  # noqa: E731  JSON turns tuples into lists
    documents.clear()
    documents.update({k: DocumentInfo(**v) for k, v in data.get("documents", {}).items()})
    quizzes.clear()
    quizzes.update({k: {"quiz": QuizResponse(**v["quiz"]), "answers": keys(v["answers"])} for k, v in data.get("quizzes", {}).items()})
    progress.clear()
    for u, ts in data.get("progress", {}).items():
        progress[u] = {t: {**d, "last": datetime.fromisoformat(d["last"]) if d.get("last") else None} for t, d in ts.items()}
    history.clear()
    history.update({u: [QuizHistoryItem(**h) for h in hs] for u, hs in data.get("history", {}).items()})
    exams.clear()
    exams.update({
        k: {"exam": ExamResponse(**v["exam"]), "answers": keys(v["answers"]), "result": ExamResult(**v["result"]) if v.get("result") else None}
        for k, v in data.get("exams", {}).items()
    })
    exam_history.clear()
    exam_history.update({u: [ExamHistoryItem(**h) for h in hs] for u, hs in data.get("exam_history", {}).items()})
