"""Mind map / flowchart of topics: a tree of concepts (root -> topics -> subtopics -> details) plus cross-links.

The frontend draws the same data two ways: a mind map (root in the middle, branches left and right)
and a top-down flowchart.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.prompts import templates
from app.routers.common import retrieve_or_404, source_for_label
from app.schemas import MindMapLink, MindMapNode, MindMapRequest, MindMapResponse, SourceRef
from app.services import mock, pipeline, store
from app.services.llm import LLMClient, get_llm
from app.services.validation import clean_mindmap

router = APIRouter(prefix="/api", tags=["mindmap"])

# A whole-document map needs passages from every part of the lecture, not just the best match for one query.
PER_TOPIC = 2
MAX_PASSAGES = 14
MIN_BUDGET_TOKENS = 3000


def document_topics(document_ids) -> list[str]:
    docs = [d for d in store.documents.values() if not document_ids or d.document_id in document_ids]
    topics = list(dict.fromkeys(t for d in docs for t in d.topics))
    return [t for t in topics if t != "General"]


def whole_document_context(document_ids, topics: list[str], budget: int) -> tuple[list[SourceRef], str]:
    """CONTEXT for a whole-document map.

    * The document(s) fit in the budget: send all of it, in page order (most lecture handouts fit).
    * Too long: a couple of passages per detected topic (round-robin, so every topic gets in before any topic
      gets a second), topped up from a general search when the topics found are few.
    """
    if get_settings().mock_retrieval:
        return retrieve_or_404("main topics, key concepts and definitions", document_ids, MAX_PASSAGES, budget)
    chunks = [c for c in pipeline.get_index().chunks if not document_ids or c.document_id in document_ids]
    if not chunks:
        raise HTTPException(404, detail="No passages found in the uploaded documents. Upload a document first.")
    if sum(pipeline.estimate_tokens(c.text) for c in chunks) <= budget:
        ordered = sorted(chunks, key=lambda c: (c.document_id, c.page, c.chunk_id))
        context, used = pipeline.build_context([pipeline._ref(c, 1.0) for c in ordered], budget)
        return used, context
    try:
        per_topic = [pipeline.retrieve(t, document_ids, PER_TOPIC) for t in topics]
        general = pipeline.retrieve("main topics, key concepts and definitions", document_ids, MAX_PASSAGES)
    except ImportError as e:
        raise HTTPException(501, detail=pipeline.missing_package_message(e))
    picked, seen = [], set()
    rounds = [[hits[r] for hits in per_topic if r < len(hits)] for r in range(PER_TOPIC)] + [general]
    for hit in (h for batch in rounds for h in batch):
        if hit.chunk_id not in seen and len(picked) < MAX_PASSAGES:
            seen.add(hit.chunk_id)
            picked.append(hit)
    context, used = pipeline.build_context(picked, budget)
    return used, context


@router.post("/mindmap", response_model=MindMapResponse, summary="Mind map / flowchart of the topics in your material")
async def mindmap(req: MindMapRequest, llm: LLMClient = Depends(get_llm)):
    topic = (req.topic or "").strip() or None
    if get_settings().use_mocks:
        return mock.mindmap(topic, req.max_nodes)

    budget = max(get_settings().context_budget_tokens, MIN_BUDGET_TOKENS)
    known = document_topics(req.document_ids)
    if topic:
        sources, context = retrieve_or_404(topic, req.document_ids, 10, budget)
    else:
        sources, context = whole_document_context(req.document_ids, known, budget)

    prompt = templates.mindmap_prompt(topic, req.max_nodes, context, known[:12])
    data = await llm.chat_json(prompt, max_tokens=2500)
    m = clean_mindmap(data, req.max_nodes, fallback_title=topic or "Mind map")
    if not m["nodes"]:
        raise HTTPException(502, detail="The model did not return a usable mind map. Try again, or pick a narrower topic.")

    nodes = [
        MindMapNode(node_id=n["id"], label=n["label"], summary=n["summary"], parent_id=n["parent"], level=n["level"],
                    source=source_for_label(n.get("source") or n["summary"], sources))
        for n in m["nodes"]
    ]
    links = [MindMapLink(from_id=l["from"], to_id=l["to"], label=l["label"]) for l in m["links"]]
    return MindMapResponse(title=m["title"], topic=topic, root_id=nodes[0].node_id, nodes=nodes, links=links, sources=sources)
