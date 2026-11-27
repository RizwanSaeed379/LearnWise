"""build_context: dedupe, merge neighbouring chunks of a page, token budget, label order."""
from app.services import pipeline
from app.services.pipeline import build_context, estimate_tokens
from app.schemas import SourceRef


def ref(no, page, text, score, doc="d"):
    return SourceRef(document_id=doc, filename="l.pdf", page=page, chunk_id=f"{doc}_c{no:04d}", snippet=text, score=score)


A = "Backpropagation applies the chain rule to compute the gradient of the loss for every weight in the network."
B_TAIL = "for every weight in the network. Gradients flow from the output layer back to the input layer."


def test_neighbouring_chunks_on_one_page_are_merged_without_repeating_the_overlap():
    ctx, used = build_context([ref(3, 1, A, 0.9), ref(4, 1, B_TAIL, 0.7)], 10_000)
    assert len(used) == 1 and used[0].chunk_id == "d_c0003+d_c0004" and used[0].score == 0.9
    assert used[0].snippet.count("for every weight in the network.") == 1
    assert used[0].snippet.endswith("back to the input layer.") and ctx.count("[S") == 1


def test_not_merged_across_pages_documents_or_gaps():
    used = build_context([ref(3, 1, A, 0.9), ref(4, 2, B_TAIL, 0.8), ref(5, 2, "Another passage about pooling layers.", 0.6),
                          ref(9, 2, "Dropout randomly zeroes activations while training.", 0.5),
                          ref(4, 1, "Max pooling shrinks the feature map size.", 0.4, doc="e")], 10_000)[1]
    assert [u.chunk_id for u in used] == ["d_c0003", "d_c0004+d_c0005", "d_c0009", "e_c0004"]


def test_duplicates_and_contained_passages_are_dropped():
    used = build_context([ref(1, 1, A, 0.9), ref(7, 3, A.upper(), 0.5), ref(8, 4, "the chain rule to compute the gradient", 0.4)], 10_000)[1]
    assert [u.chunk_id for u in used] == ["d_c0001"]


def test_longer_lower_scored_passage_replaces_one_it_contains_and_keeps_best_score():
    used = build_context([ref(1, 1, "chain rule to compute the gradient", 0.9), ref(6, 3, A, 0.5)], 10_000)[1]
    assert [(u.chunk_id, u.score) for u in used] == [("d_c0006", 0.9)]


def test_budget_adds_best_first_and_stops():
    texts = [f"Passage number {i} " + "word " * 100 for i in range(5)]
    srcs = [ref(i * 10, i + 1, t, 0.9 - i * 0.1) for i, t in enumerate(texts)]
    one = estimate_tokens(f"[S1] (l.pdf, page 1)\n{texts[0]}\n\n")
    ctx, used = build_context(srcs, budget_tokens=2 * one + 10)
    assert [u.page for u in used] == [1, 2]  # the best two, in the order retrieval ranked them
    assert estimate_tokens(ctx) <= 2 * one + 10
    assert ctx.index("[S1] (l.pdf, page 1)") < ctx.index("[S2] (l.pdf, page 2)")


def test_best_passage_is_cut_to_fit_a_tiny_budget():
    ctx, used = build_context([ref(1, 1, "word " * 400, 0.9), ref(2, 5, "other", 0.8)], budget_tokens=60)
    assert len(used) == 1 and 0 < len(used[0].snippet) < 400 * 5 and estimate_tokens(ctx) <= 70


def test_retrieval_order_wins_over_cosine_score():
    # hybrid/re-ranked order can differ from the cosine in .score: S1 must be retrieval's first pick
    used = build_context([ref(1, 2, "Keyword match passage about beta1.", 0.4), ref(5, 7, "Dense favourite passage.", 0.8)], 10_000)[1]
    assert [u.page for u in used] == [2, 7]


def test_default_budget_comes_from_settings(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "context_budget_tokens", 40)
    assert len(build_context([ref(1, 1, "word " * 50, 0.9), ref(2, 4, "word two " * 30, 0.8)])[1]) == 1


def test_empty():
    ctx, used = build_context([], 100)
    assert used == [] and ctx == f"{pipeline.DOC_OPEN}\n\n{pipeline.DOC_CLOSE}"


def test_real_overlapping_chunks_rejoin_to_the_page_text():
    text = " ".join(f"Sentence {i} talks about topic number {i * 7} and its weight {i * 3}." for i in range(60))
    chunks = pipeline.chunk_pages("doc", "l.pdf", [(3, text)])
    assert len(chunks) > 2
    refs = [SourceRef(document_id="doc", filename="l.pdf", page=3, chunk_id=c.chunk_id, snippet=c.text, score=0.5) for c in chunks]
    used = build_context(refs, 10_000)[1]
    assert len(used) == 1 and used[0].snippet == pipeline._clean(text)
