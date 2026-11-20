"""Graded mock exam: personalised question plan + marking.

Personalisation
  * candidate topics = the ones the student picked, or else weak topics first
    (lowest mastery), then document topics they have not practised yet
  * each topic gets questions in proportion to (1.25 - mastery), so a topic at
    30% mastery gets about 3x the questions of a topic at 90%
  * with difficulty="adaptive", each topic's difficulty follows its mastery
    (easy < 40% <= medium < 75% <= hard)

Marking
  * MCQ: 1 mark, auto-marked against the stored key
  * short answer: 3 marks, the LLM scores the fraction of key points covered
    (mock mode uses keyword overlap), rounded to the nearest half mark
"""
from app.schemas import ExamTopicPlan, ExamTopicScore
from app.services import adaptive, store

MCQ_MARKS = 1.0
SHORT_MARKS = 3.0
PASS_MARK = 50.0
GRADES = [(85, "A"), (70, "B"), (55, "C"), (40, "D")]


def difficulty_for(m: float) -> str:
    return "easy" if m < 0.4 else "medium" if m < 0.75 else "hard"


def grade_for(pct: float) -> str:
    return next((g for cut, g in GRADES if pct >= cut), "F")


def round_half(x: float) -> float:
    return round(x * 2) / 2


def _split(total: int, weights: list[float]) -> list[int]:
    """Share `total` questions across topics by weight (largest remainder, ties -> earlier/weaker topic)."""
    if total <= 0 or not weights:
        return [0] * len(weights)
    s = sum(weights)
    raw = [total * w / s for w in weights]
    out = [int(r) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - out[i]), i))
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def candidate_topics(user_id: str, chosen: list[str] | None, document_ids: list[str] | None, max_topics: int) -> list[tuple[str, str]]:
    """[(topic, why_included)], weakest first, at most max_topics."""
    if chosen:
        seen, out = set(), []
        for t in (x.strip() for x in chosen):
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append((t, "picked"))
        return out[:max_topics]

    out = [(p.topic, "history") for p in adaptive.topic_progress(user_id)]  # weakest first
    known = {t.lower() for t, _ in out}
    docs = [d for d in store.documents.values() if not document_ids or d.document_id in document_ids]
    for d in docs:
        for t in d.topics:
            if t.lower() not in known:
                known.add(t.lower())
                out.append((t, "new"))
    # Weak and unseen topics first; strong topics only fill remaining slots.
    weak = [x for x in out if x[1] == "history" and _mastery(user_id, x[0]) < adaptive.WEAK_THRESHOLD]
    new = [x for x in out if x[1] == "new"]
    strong = [x for x in out if x[1] == "history" and x not in weak]
    return (weak + new + strong)[:max_topics] or [("General review", "new")]


def _mastery(user_id: str, topic: str) -> float:
    t = store.progress.get(user_id, {}).get(topic)
    return adaptive.mastery(t["attempts"], t["correct"]) if t else 0.5


def build_plan(user_id: str, chosen, document_ids, max_topics: int, num_mcq: int, num_short: int, difficulty: str) -> list[ExamTopicPlan]:
    topics = candidate_topics(user_id, chosen, document_ids, max_topics)
    masteries = [_mastery(user_id, t) for t, _ in topics]
    weights = [1.25 - m for m in masteries]
    mcq = _split(num_mcq, weights)
    short = _split(num_short, weights)

    plan = []
    for (topic, why), m, nm, ns in zip(topics, masteries, mcq, short):
        if nm + ns == 0:
            continue
        p = store.progress.get(user_id, {}).get(topic)
        if why == "picked":
            reason = "You chose this topic."
        elif why == "new" or not p:
            reason = "You haven't been tested on this yet."
        elif m < adaptive.WEAK_THRESHOLD:
            reason = f"Weak topic: {round(m * 100)}% mastery after {p['attempts']} questions, so it gets more questions."
        else:
            reason = f"Strong topic ({round(m * 100)}% mastery), included to check you still remember it."
        plan.append(ExamTopicPlan(topic=topic, mastery=m, difficulty=difficulty_for(m) if difficulty == "adaptive" else difficulty, num_mcq=nm, num_short=ns, reason=reason))
    return plan


def topic_scores(results) -> list[ExamTopicScore]:
    agg: dict[str, list[float]] = {}
    for r in results:
        a = agg.setdefault(r.topic, [0.0, 0.0])
        a[0] += r.marks_awarded
        a[1] += r.marks_available
    rows = [ExamTopicScore(topic=t, marks_awarded=a, marks_available=b, percentage=round(100 * a / b, 1) if b else 0.0) for t, (a, b) in agg.items()]
    return sorted(rows, key=lambda r: r.percentage)


def recommendations(scores: list[ExamTopicScore], results) -> list[str]:
    recs = []
    for s in scores:
        if s.percentage >= 60:
            continue
        missed = [p for r in results if r.topic == s.topic for p in r.missing_points][:3]
        tip = f" Points you missed: {'; '.join(missed)}." if missed else ""
        recs.append(f"Revise {s.topic} ({s.percentage}%): read the exam-style notes on it, then use 'Practise my weak topics'.{tip}")
    if not recs:
        recs.append("Well done. Try another exam at a harder difficulty, or add more topics.")
    return recs
