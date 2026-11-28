"""Tests the real (non-mock) code path with a fake LLM, so no GPU is needed.

USE_MOCKS=false + MOCK_RETRIEVAL=true: routes build prompts, call the LLM,
validate its JSON and map [S1] labels back to pages.
"""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.llm import get_llm


class FakeLLM:
    async def chat(self, messages, **kw):
        prompt = messages[-1]["content"]
        if "QUESTION:" in prompt:
            return "Backprop uses the chain rule [S1]."
        return "Simpler explanation with an analogy."

    async def chat_json(self, messages, **kw):
        prompt = messages[-1]["content"]
        if "flashcards" in prompt:
            return {"cards": [{"front": "Chain rule", "back": "Derivative of composed functions.", "source": "S2"}, {"front": "", "back": "dropped"}]}
        if "multiple-choice" in prompt:
            return {"questions": [
                {"type": "mcq", "question": "Q1?", "options": ["a", "b", "c", "d"], "answer": "B", "explanation": "e", "source": "S1"},
                {"type": "mcq", "question": "bad, 3 options", "options": ["a", "b", "c"], "answer": "0"},
                {"type": "short", "question": "Explain it.", "answer": "chain rule gradients", "explanation": "e", "source": "S2"},
            ]}
        if "Grade the student" in prompt:
            return {"score": 0.8, "feedback": "Good, mention weight updates too."}
        return {"title": "Backprop", "sections": [{"heading": "Idea", "content": "Chain rule [S1]", "bullets": [], "key_terms": []}]}


@pytest.fixture
def c(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "use_mocks", False)
    monkeypatch.setattr(s, "mock_retrieval", True)
    app.dependency_overrides[get_llm] = lambda: FakeLLM()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ask_returns_sources(c):
    body = c.post("/api/ask", json={"question": "What is backprop?"}).json()
    assert body["answer"] == "Backprop uses the chain rule [S1]." and body["sources"]


def test_notes(c):
    assert c.post("/api/notes", json={"topic": "Backprop", "style": "detailed"}).json()["sections"][0]["heading"] == "Idea"


def test_flashcards_validated_and_cited(c):
    cards = c.post("/api/flashcards", json={"topic": "Backprop", "count": 2}).json()["cards"]
    assert len(cards) == 1 and cards[0]["source"]["page"] == 8  # S2 -> second passage (page 8)


def test_quiz_validation_and_grading(c):
    q = c.post("/api/quiz", json={"topic": "Backprop", "num_mcq": 2, "num_short": 1, "user_id": "llm"}).json()
    assert [x["type"] for x in q["questions"]] == ["mcq", "short"]  # 3-option MCQ dropped
    ans = [{"question_id": q["questions"][0]["question_id"], "answer": "1"}, {"question_id": q["questions"][1]["question_id"], "answer": "chain rule"}]
    res = c.post(f"/api/quiz/{q['quiz_id']}/submit", json={"user_id": "llm", "answers": ans}).json()
    assert res["results"][0]["correct"]  # letter "B" normalised to index "1"
    assert res["results"][1]["score"] == 0.8


def test_real_retrieval_with_no_documents_gives_404(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "use_mocks", False)
    monkeypatch.setattr(s, "mock_retrieval", False)
    monkeypatch.setattr(s, "data_dir", s.data_dir + "/empty")
    r = TestClient(app).post("/api/ask", json={"question": "What is backprop?"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_extra_questions_from_the_model_are_trimmed(c):
    q = c.post("/api/quiz", json={"topic": "Backprop", "num_mcq": 1, "num_short": 0}).json()
    assert [x["type"] for x in q["questions"]] == ["mcq"]


def test_qwen3_requests_turn_thinking_off(monkeypatch):
    """reasoning_effort=none is the switch Ollama's /v1 endpoint honours; without it Qwen3 may spend max_tokens
    thinking and return empty content."""
    import asyncio

    import httpx

    from app.services.llm import LLMClient

    sent = []

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "<think>\n\n</think>\n\nWhere does photolysis happen?"}}]}

    async def fake_post(self, url, json=None, headers=None):
        sent.append(json)
        return Resp()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    s = get_settings()
    monkeypatch.setattr(s, "llm_model", "qwen3:8b")
    monkeypatch.setattr(s, "llm_disable_thinking", True)
    text = asyncio.run(LLMClient(s).chat([{"role": "user", "content": "hi"}], max_tokens=150))
    assert text == "Where does photolysis happen?"
    assert sent[0]["reasoning_effort"] == "none" and sent[0]["messages"][-1]["content"].endswith("/no_think")

    monkeypatch.setattr(s, "llm_model", "llama3.1:8b")  # other models are left alone
    asyncio.run(LLMClient(s).chat([{"role": "user", "content": "hi"}]))
    assert "reasoning_effort" not in sent[1]
