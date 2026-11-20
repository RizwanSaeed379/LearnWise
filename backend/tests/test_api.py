"""Run from backend/:  pytest -q      (uses mock mode, no LLM needed)"""
import os

os.environ["USE_MOCKS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)


def test_health():
    r = c.get("/api/health")
    assert r.status_code == 200 and r.json()["mock_mode"] is True


def test_upload_and_list():
    r = c.post("/api/documents", files={"file": ("week1.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert r.status_code == 201
    doc_id = r.json()["document_id"]
    ids = [d["document_id"] for d in c.get("/api/documents").json()["documents"]]
    assert doc_id in ids


def test_upload_rejects_wrong_type():
    r = c.post("/api/documents", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_file"


def test_ask_has_sources():
    r = c.post("/api/ask", json={"question": "What is backpropagation?"})
    body = r.json()
    assert r.status_code == 200 and body["sources"] and body["sources"][0]["page"] >= 1


def test_validation_error_shape():
    r = c.post("/api/ask", json={"question": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_notes_styles():
    for style in ("concise", "detailed", "exam"):
        r = c.post("/api/notes", json={"topic": "Backpropagation", "style": style})
        assert r.status_code == 200 and r.json()["style"] == style


def test_quiz_flow_updates_progress():
    q = c.post("/api/quiz", json={"topic": "Backpropagation", "difficulty": "easy", "num_mcq": 2, "num_short": 1, "user_id": "t1"}).json()
    assert len(q["questions"]) == 3 and "answer" not in q["questions"][0]
    answers = [{"question_id": x["question_id"], "answer": "3" if x["type"] == "mcq" else "no idea"} for x in q["questions"]]
    res = c.post(f"/api/quiz/{q['quiz_id']}/submit", json={"user_id": "t1", "answers": answers}).json()
    assert res["total"] == 3
    prog = c.get("/api/progress/t1").json()
    assert prog["topics"][0]["topic"] == "Backpropagation" and prog["recent_quizzes"]


def test_flashcards():
    r = c.post("/api/flashcards", json={"topic": "Overfitting", "count": 5})
    assert len(r.json()["cards"]) == 5


def test_practice_targets_weak_topic():
    q = c.post("/api/quiz", json={"topic": "Dropout", "num_mcq": 2, "num_short": 0, "user_id": "t2"}).json()
    wrong = [{"question_id": x["question_id"], "answer": "9"} for x in q["questions"]]
    c.post(f"/api/quiz/{q['quiz_id']}/submit", json={"user_id": "t2", "answers": wrong})
    p = c.post("/api/practice", json={"user_id": "t2", "max_topics": 1, "questions_per_topic": 2}).json()
    assert p["selected"][0]["topic"] == "Dropout" and len(p["quiz"]["questions"]) == 2
