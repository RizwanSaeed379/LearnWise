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
    except NotImplementedError as e:
        raise HTTPException(501, detail=f"Real pipeline not implemented yet ({e}). Set USE_MOCKS=true.")
    if not sources:
        raise HTTPException(404, detail="No relevant passages found in the uploaded documents.")
    return sources, pipeline.format_context(sources)


def source_for_label(label, sources: list[SourceRef]):
    """Map 'S2' from the LLM back to the second retrieved passage."""
    m = _LABEL.search(str(label or ""))
    if m and 1 <= int(m.group(1)) <= len(sources):
        return sources[int(m.group(1)) - 1]
    return sources[0] if sources else None
