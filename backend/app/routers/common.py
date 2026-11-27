"""Helpers shared by the real (non-mock) routes."""
import re

from fastapi import HTTPException

from app.config import get_settings
from app.schemas import SourceRef
from app.services import mock, pipeline

_LABEL = re.compile(r"S(\d+)")


def retrieve_or_404(query: str, document_ids, top_k: int) -> tuple[list[SourceRef], str]:
    if get_settings().mock_retrieval:
        sources = mock.sources(min(top_k, 3))
        return sources, pipeline.format_context(sources)
    try:
        sources = pipeline.retrieve(query, document_ids, top_k)
    except ImportError as e:
        raise HTTPException(501, detail=pipeline.missing_package_message(e))
    if not sources:
        raise HTTPException(404, detail="No relevant passages found in the uploaded documents. Upload a document first, or rephrase.")
    return sources, pipeline.format_context(sources)


def source_for_label(label, sources: list[SourceRef]):
    """Map 'S2' from the LLM back to the second retrieved passage.

    A missing or out-of-range label (e.g. 'S7' with 5 passages) gives None rather than a guess:
    pointing it at S1 would show a page that may not say what the item claims."""
    m = _LABEL.search(str(label or ""))
    if m and 1 <= int(m.group(1)) <= len(sources):
        return sources[int(m.group(1)) - 1]
    return None


_WORD = re.compile(r"[a-z0-9]+")


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(str(text).lower()) if len(w) > 3}


def source_for_answer(label, answer_text: str, sources: list[SourceRef]):
    """Like source_for_label, but if the labelled passage does not contain the answer's
    key words and another retrieved passage does, point to that one instead.
    LLMs often label every question S1 even when the fact is in S3."""
    picked = source_for_label(label, sources)
    words = _content_words(answer_text)
    if not words or not sources:
        return picked
    overlap = lambda s: len(words & _content_words(s.snippet)) / len(words)
    best = max(sources, key=overlap)
    return best if picked is None or overlap(best) > overlap(picked) else picked
