"""Follow-up memory for /api/ask.

The frontend sends the last few exchanges with each question. They are used for two things only:
  1. rewriting a follow-up ("why is that important?") into a standalone question before searching, so
     retrieval finds the right passages;
  2. showing the model what the question refers to.
They are NEVER a source of facts: the answer must still come from, and is still verified against, the
passages retrieved for the current question.

Safety: earlier answers were written from the student's documents, so a document's hidden instruction could
have been echoed into one. History therefore sits in its own <history> block, with any <history>/<documents>
tags inside it neutralised (the same defence as the <documents> block), and the model is told to treat it as
conversation only. Old [S#] labels are removed, because they pointed at the previous question's passages.
"""
from __future__ import annotations

import re

from app.schemas import AskTurn

HISTORY_OPEN, HISTORY_CLOSE = "<history>", "</history>"
_TAGS = re.compile(r"</?\s*(history|documents)\s*>", re.I)
_LABEL = re.compile(r"\s*\[S\d+\]")
_MAX_ANSWER_CHARS = 500

# A question that leans on the conversation: a pronoun or "that/those" pointing back, an elliptical opener
# ("and the second stage?", "what about CO2?"), a request about the last answer ("explain more", "simpler"),
# or a very short question ("why?", "an example?"). "Why is the Calvin cycle light-independent?" names its subject,
# so it is searched as asked (no extra model call).
_REFERS_BACK = re.compile(
    r"\b(it|its|it's|itself|that|this|these|those|they|them|their|theirs|he|she|his|her|the former|the latter|"
    r"above|previous|same|the other)\b",
    re.I,
)
_ELLIPTICAL = re.compile(
    r"^\s*(and|but|so|also|then|what about|how about|what else|anything else|more|"
    r"explain (more|further|again|in detail|simply)|elaborate|simpler|in simpler|example|give (me )?an? example|"
    r"tell me more|go on|continue|really|such as|like what|compared to|vs\.?|versus)\b",
    re.I,
)


def defang(text: str) -> str:
    """Stop history text from closing or opening a prompt block itself."""
    return _TAGS.sub("[tag removed]", str(text))


def trim_history(history: list[AskTurn], turns: int, max_chars: int) -> list[AskTurn]:
    """The last `turns` exchanges, labels stripped, long answers shortened; oldest dropped first to fit max_chars."""
    if turns <= 0:
        return []
    kept: list[AskTurn] = []
    for t in history[-turns:]:
        answer = _LABEL.sub("", t.answer).strip()
        if len(answer) > _MAX_ANSWER_CHARS:
            answer = answer[:_MAX_ANSWER_CHARS].rsplit(" ", 1)[0] + " …"
        kept.append(AskTurn(question=t.question.strip()[:400], answer=answer))
    while kept and sum(len(t.question) + len(t.answer) for t in kept) > max_chars:
        kept.pop(0)
    return kept


def is_follow_up(question: str, history: list[AskTurn]) -> bool:
    """True when the question probably can't be searched on its own. False without history."""
    if not history:
        return False
    q = question.strip()
    return bool(_REFERS_BACK.search(q) or _ELLIPTICAL.search(q) or len(q.split()) <= 3)


def history_block(history: list[AskTurn]) -> str:
    """Oldest first; the last exchange is marked, because short follow-ups ("why?", "and RuBP?") almost always
    refer to it, and without the mark the model sometimes picks an older exchange."""
    n = len(history)
    body = "\n\n".join(
        f"[{'MOST RECENT' if i == n - 1 else 'earlier'}]\nStudent: {defang(t.question)}\nLearnWise: {defang(t.answer)}"
        for i, t in enumerate(history)
    )
    return f"{HISTORY_OPEN}\n{body}\n{HISTORY_CLOSE}"


def clean_rewrite(text: str, original: str) -> str:
    """The model's standalone question, or the original when the rewrite is unusable."""
    line = next((l for l in str(text).splitlines() if l.strip()), "")
    line = re.sub(r"^\s*(standalone question|question|rewritten)\s*:\s*", "", line, flags=re.I)
    line = line.strip().strip("\"'`").strip()
    bad = (
        len(line) < 3
        or len(line) > max(300, 4 * len(original))
        or "NOT_FOUND" in line
        or _TAGS.search(line)
        or line.lower().startswith(("i ", "sorry", "as an ai"))
    )
    return original if bad else line


def fallback_query(question: str, history: list[AskTurn]) -> str:
    """When the model couldn't rewrite a follow-up, search with the previous question in front of it:
    "What is photolysis? Where does it happen?" still finds the photolysis passages, while "Where does it
    happen?" on its own matches whatever passage talks about 'happening'."""
    return f"{history[-1].question.rstrip()} {question}" if history else question
