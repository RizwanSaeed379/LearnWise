"""Adaptive practice logic (owner: Sana).

mastery = (correct + 1) / (attempts + 2)   <- "Laplace smoothing": a topic you
tried once and got wrong is weak (0.33), not hopeless (0.0); a brand new topic
starts at 0.5.  Weak = mastery < 0.6.  Practice picks the weakest topics first.
"""
from app.schemas import TopicProgress
from app.services import store

WEAK_THRESHOLD = 0.6


def mastery(attempts: int, correct: float) -> float:
    return round((correct + 1) / (attempts + 2), 3)


def topic_progress(user_id: str) -> list[TopicProgress]:
    rows = [
        TopicProgress(
            topic=topic,
            attempts=t["attempts"],
            correct=t["correct"],
            mastery=mastery(t["attempts"], t["correct"]),
            last_practiced=t["last"],
        )
        for topic, t in store.progress.get(user_id, {}).items()
    ]
    return sorted(rows, key=lambda r: r.mastery)


def weak_topics(user_id: str) -> list[str]:
    return [r.topic for r in topic_progress(user_id) if r.mastery < WEAK_THRESHOLD]


def pick_practice_topics(user_id: str, max_topics: int) -> list[TopicProgress]:
    """Weakest topics first. TODO(Sana): also favour topics not practised recently."""
    return topic_progress(user_id)[:max_topics]
