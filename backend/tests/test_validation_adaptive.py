from datetime import datetime, timedelta, timezone

from app.schemas import TopicProgress
from app.services import adaptive
from app.services.validation import clean_cards, clean_quiz_items


def mcq(**kw):
    return {"type": "mcq", "question": "Q?", "options": ["a", "b", "c", "d"], "answer": "0", "explanation": "e", **kw}


def test_mcq_fixes_and_drops():
    out = clean_quiz_items([
        mcq(question="Prefixed", options=["A) red", "B) green", "C) blue", "D) black"], answer="C"),
        mcq(question="Text answer", answer="c"),  # letter
        mcq(question="Option text", options=["Chain rule", "Bayes", "Sum", "Mean"], answer="chain rule"),
        mcq(question="Dupes", options=["a", "A", "c", "d"]),  # duplicate options -> dropped
        mcq(question="Empty", options=["a", "", "c", "d"]),
        mcq(question="Prefixed"),  # repeated question -> dropped
        {"type": "essay", "question": "x", "answer": "y"},
        "not a dict",
    ])
    assert [q["question"] for q in out] == ["Prefixed", "Text answer", "Option text"]
    assert out[0]["options"] == ["red", "green", "blue", "black"] and out[0]["answer"] == "2"
    assert out[1]["answer"] == "2" and out[2]["answer"] == "0"


def test_cards_dedupe_and_trim():
    cards = clean_cards([{"front": " LR ", "back": "step size"}, {"front": "lr", "back": "dup"}, {"front": "x", "back": ""}, None])
    assert cards == [{"front": "LR", "back": "step size"}]


def test_practice_prefers_stale_topics_at_similar_mastery():
    now = datetime.now(timezone.utc)
    fresh = TopicProgress(topic="fresh", attempts=4, correct=1.5, mastery=0.42, last_practiced=now)
    stale = TopicProgress(topic="stale", attempts=4, correct=1.6, mastery=0.44, last_practiced=now - timedelta(days=5))
    much_weaker = TopicProgress(topic="weak", attempts=4, correct=0.0, mastery=0.17, last_practiced=now)
    order = sorted([fresh, stale, much_weaker], key=lambda r: adaptive.priority(r, now))
    assert [r.topic for r in order] == ["weak", "stale", "fresh"]
