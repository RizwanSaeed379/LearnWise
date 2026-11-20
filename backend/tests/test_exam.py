"""Graded mock exam: personalisation, marking and grading."""
import os

os.environ["USE_MOCKS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services import exam as ex  # noqa: E402
from app.services import store  # noqa: E402
from app.services.llm import get_llm  # noqa: E402

c = TestClient(app)


def _answer_all(exam, mcq="0", short="chain rule gradients update weights"):
    return [{"question_id": q["question_id"], "answer": mcq if q["type"] == "mcq" else short} for q in exam["questions"]]


def test_create_exam_hides_answers_and_counts_marks():
    e = c.post("/api/exam", json={"user_id": "e1", "topics": ["Backpropagation", "Dropout"], "num_mcq": 6, "num_short": 2}).json()
    qs = e["questions"]
    assert len(qs) == 8 and all("answer" not in q for q in qs)
    assert [q["type"] for q in qs] == ["mcq"] * 6 + ["short"] * 2  # MCQs first
    assert e["total_marks"] == 6 * 1 + 2 * 3
    assert {p["topic"] for p in e["plan"]} == {"Backpropagation", "Dropout"}


def test_submit_marks_grades_and_updates_progress():
    e = c.post("/api/exam", json={"user_id": "e2", "topics": ["Backpropagation"], "num_mcq": 4, "num_short": 1}).json()
    # mock bank answers are 0,1,2,3 in order: answer the first two right, last two wrong
    key = {0: "0", 1: "1", 2: "0", 3: "0"}
    mcqs = [q for q in e["questions"] if q["type"] == "mcq"]
    answers = [{"question_id": q["question_id"], "answer": key[i]} for i, q in enumerate(mcqs)]
    answers.append({"question_id": e["questions"][-1]["question_id"], "answer": ""})  # blank short answer
    r = c.post(f"/api/exam/{e['exam_id']}/submit", json={"user_id": "e2", "answers": answers, "time_taken_seconds": 60})
    res = r.json()
    assert r.status_code == 200
    assert res["marks_awarded"] == 2 and res["total_marks"] == 7
    assert res["percentage"] == round(100 * 2 / 7, 1) and res["grade"] == "F" and not res["passed"]
    assert res["results"][-1]["marks_awarded"] == 0 and res["results"][-1]["feedback"].startswith("No answer")
    assert res["weak_topics"] == ["Backpropagation"] and res["recommendations"]
    assert c.get("/api/progress/e2").json()["topics"][0]["attempts"] == 5
    assert c.get("/api/exam/history/e2").json()["exams"][0]["grade"] == "F"
    assert c.get(f"/api/exam/{e['exam_id']}/result").json()["percentage"] == res["percentage"]


def test_cannot_submit_twice():
    e = c.post("/api/exam", json={"user_id": "e3", "topics": ["Overfitting"], "num_mcq": 1, "num_short": 0}).json()
    c.post(f"/api/exam/{e['exam_id']}/submit", json={"user_id": "e3", "answers": _answer_all(e)})
    r = c.post(f"/api/exam/{e['exam_id']}/submit", json={"user_id": "e3", "answers": _answer_all(e)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


def test_unknown_exam_and_empty_exam():
    assert c.post("/api/exam/exam_nope/submit", json={"answers": []}).status_code == 404
    r = c.post("/api/exam", json={"num_mcq": 0, "num_short": 0})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_personalised_plan_puts_weak_topic_first_with_more_questions():
    store.progress["e4"] = {
        "Gradient descent": {"attempts": 10, "correct": 9.0, "last": None},  # strong
        "Backpropagation": {"attempts": 10, "correct": 2.0, "last": None},  # weak
    }
    e = c.post("/api/exam", json={"user_id": "e4", "num_mcq": 10, "num_short": 2, "max_topics": 3, "difficulty": "adaptive"}).json()
    plan = e["plan"]
    assert plan[0]["topic"] == "Backpropagation" and plan[0]["difficulty"] == "easy"
    weak = plan[0]["num_mcq"] + plan[0]["num_short"]
    others = [p["num_mcq"] + p["num_short"] for p in plan[1:]]
    assert all(weak > o for o in others)
    assert "Gradient descent" not in [p["topic"] for p in plan]  # unseen topics fill slots before strong ones


def test_split_is_exact_and_weighted():
    assert ex._split(10, [1.0, 0.5, 0.5]) == [5, 3, 2]
    assert sum(ex._split(7, [0.9, 0.3, 0.6])) == 7
    assert ex.grade_for(85) == "A" and ex.grade_for(39.9) == "F"


class FakeLLM:
    async def chat(self, messages, **kw):
        return "x"

    async def chat_json(self, messages, **kw):
        p = messages[-1]["content"]
        if "mock exam" in p:
            return {"score": 0.5, "feedback": "Half the key points.", "missing_points": ["weight updates"]}
        return {"questions": [
            {"type": "mcq", "question": "Q?", "options": ["a", "b", "c", "d"], "answer": "2", "explanation": "e", "source": "S1"},
            {"type": "short", "question": "Explain.", "answer": "ref", "explanation": "e", "source": "S2"},
        ]}


@pytest.fixture
def llm_client(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "use_mocks", False)
    monkeypatch.setattr(s, "mock_retrieval", True)
    app.dependency_overrides[get_llm] = lambda: FakeLLM()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_llm_path_marks_short_answers_with_rubric(llm_client):
    e = llm_client.post("/api/exam", json={"user_id": "e5", "topics": ["Backprop"], "num_mcq": 1, "num_short": 1}).json()
    res = llm_client.post(f"/api/exam/{e['exam_id']}/submit", json={"user_id": "e5", "answers": _answer_all(e, mcq="2", short="something")}).json()
    short = res["results"][1]
    assert res["results"][0]["marks_awarded"] == 1
    assert short["marks_awarded"] == 1.5 and short["missing_points"] == ["weight updates"]  # 0.5 * 3 marks
    assert res["marks_awarded"] == 2.5 and res["total_marks"] == 4 and res["grade"] == "C"  # 62.5%
