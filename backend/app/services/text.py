"""Small text helpers shared by keyword retrieval (BM25) and the answer verifier.

Same light normalisation as eval/run_eval.py: lower case, drop stop words and very short words,
strip a few English suffixes so 'layers'/'layer' and 'detects'/'detect' match.
"""
from __future__ import annotations

import re

STOP = set(
    "the a an of to in and or is are was were be by for with on at as it its this that from which what why "
    "how when who does do can into than then each".split()
)
_WORD = re.compile(r"[a-z0-9]+")
_CITE = re.compile(r"\[S\d+\]")


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def words(text: str) -> list[str]:
    """Content words of a text, stemmed. Used as BM25 tokens and for support checks."""
    return [stem(w) for w in _WORD.findall(str(text).lower()) if len(w) > 2 and w not in STOP]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(text).replace("\n", " ")) if len(s.strip()) > 3]


def support(sentence: str, passages: list[str]) -> float:
    """Fraction of the sentence's content words (citations removed) that appear in the passages. 1.0 if it has none."""
    ws = set(words(_CITE.sub("", sentence)))
    if not ws:
        return 1.0
    pool = set(words(" ".join(passages)))
    return len(ws & pool) / len(ws)
