"""Hybrid retrieval: BM25 + dense fused with RRF, optional re-ranker, MIN_SCORE and document filters."""
import numpy as np
import pytest

from app.config import get_settings
from app.services import pipeline
from app.services.pipeline import BM25, Chunk, rrf

TEXTS = {
    "a": "Gradient descent updates every weight using the learning rate and the gradient of the loss.",
    "b": "The Adam optimiser keeps running averages of gradients; its beta1 parameter is usually 0.9.",
    "c": "Max pooling keeps the largest value in each window of the feature map.",
}


class FixedEmbedder:
    """Hand-made vectors: the query 'beta1 ...' is (deliberately) closest to chunk a, not b."""

    VEC = {"a": [1.0, 0.0, 0.0], "b": [0.6, 0.8, 0.0], "c": [0.0, 0.0, 1.0]}

    def encode(self, texts, query=False):
        out = []
        for t in texts:
            key = next((k for k, v in TEXTS.items() if v == t), None)
            if key:
                out.append(self.VEC[key])
            elif "football" in t:
                out.append([0.0, -1.0, 0.0])  # unrelated question: cosine <= 0 with everything
            elif "pooling" in t:
                out.append([0.1, 0.0, 1.0])
            else:
                out.append([0.95, 0.3, 0.05])
        v = np.asarray(out, dtype="float32")
        return v / np.linalg.norm(v, axis=1, keepdims=True)


@pytest.fixture
def idx(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "data_dir", str(tmp_path))
    monkeypatch.setattr(s, "min_score", 0.2)
    monkeypatch.setattr(s, "hybrid_retrieval", True)
    monkeypatch.setattr(s, "rerank_model", "")
    pipeline._index = None
    pipeline.set_embedder(FixedEmbedder())
    pipeline.set_reranker(None)
    chunks = [Chunk(f"doc1_c000{i}", "doc1" if k != "c" else "doc2", "l.pdf", i + 1, TEXTS[k]) for i, k in enumerate("abc")]
    pipeline.index_chunks(chunks)
    yield s
    pipeline._index = None
    pipeline.set_embedder(None)
    pipeline.set_reranker(None)


def test_bm25_prefers_rare_exact_term():
    bm = BM25(list(TEXTS.values()))
    sc = bm.scores("What is beta1 in Adam?")
    assert int(np.argmax(sc)) == 1 and sc[0] == 0 and sc[2] == 0


def test_bm25_empty_corpus_and_unknown_words():
    assert len(BM25([]).scores("anything")) == 0
    assert not BM25(list(TEXTS.values())).scores("zebra quantum").any()


def test_rrf_combines_rankings():
    fused = rrf([[0, 1, 2], [1]], k=60)
    assert [i for i, _ in fused] == [1, 0, 2]
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)


def test_hybrid_finds_keyword_match_that_dense_ranks_second(idx, monkeypatch):
    q = "What value does beta1 usually take?"
    monkeypatch.setattr(idx, "hybrid_retrieval", False)
    assert pipeline.retrieve(q, None, 1)[0].chunk_id == "doc1_c0000"  # dense alone picks the wrong chunk
    monkeypatch.setattr(idx, "hybrid_retrieval", True)
    top = pipeline.retrieve(q, None, 3)
    assert top[0].chunk_id == "doc1_c0001"
    assert 0 <= top[0].score <= 1 and top[0].score == pytest.approx(0.6 * 0.95 + 0.8 * 0.3, abs=0.02)  # score stays the cosine


def test_min_score_still_rejects_out_of_scope_questions(idx):
    assert pipeline.retrieve("Who won the football world cup?", None, 5) == []


def test_document_filter_applies_to_keyword_hits(idx):
    hits = pipeline.retrieve("largest value in the pooling window beta1", ["doc2"], 5)
    assert {h.document_id for h in hits} == {"doc2"}


def test_reranker_reorders_and_failure_falls_back(idx):
    class PreferC:
        def score(self, query, texts):
            return [10.0 if "pooling" in t else 0.0 for t in texts]

    class Broken:
        def score(self, query, texts):
            raise RuntimeError("model not downloaded")

    q = "What value does beta1 usually take?"
    fused = [h.chunk_id for h in pipeline.retrieve(q, None, 3)]
    pipeline.set_reranker(PreferC())
    # c (pooling) has cosine 0.05 < MIN_SCORE, so it is never a candidate; a and b keep their order
    assert [h.chunk_id for h in pipeline.retrieve(q, None, 3)] == fused
    pipeline.set_reranker(type("PreferA", (), {"score": lambda self, q, t: [1.0 if "Gradient descent" in x else 0.0 for x in t]})())
    assert pipeline.retrieve(q, None, 3)[0].chunk_id == "doc1_c0000"
    pipeline.set_reranker(Broken())
    assert [h.chunk_id for h in pipeline.retrieve(q, None, 3)] == fused


def test_configured_reranker_that_cannot_load_is_skipped(idx, monkeypatch):
    monkeypatch.setattr(idx, "rerank_model", "no-such/model")
    monkeypatch.setattr(pipeline.CrossEncoderReranker, "score", lambda self, q, t: (_ for _ in ()).throw(ImportError("sentence_transformers")))
    first = pipeline.retrieve("What value does beta1 usually take?", None, 2)
    assert first[0].chunk_id == "doc1_c0001"
    assert pipeline.get_reranker() is None  # not retried on the next question


def test_bm25_rebuilds_after_delete(idx):
    pipeline.delete_document("doc1")
    assert pipeline.retrieve("What value does beta1 usually take?", None, 3) == []
