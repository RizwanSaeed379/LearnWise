"""The real ingestion + retrieval pipeline on real PDF/PPTX files, with a tiny fake embedder
(bag of hashed words) so the test needs no model download. Run: pytest -q tests/test_pipeline.py"""
import hashlib
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

pymupdf = pytest.importorskip("pymupdf")
pptx = pytest.importorskip("pptx")

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services import pipeline, store  # noqa: E402
from app.services.llm import get_llm  # noqa: E402


class HashEmbedder:
    """Same words -> similar vectors. Good enough to check that retrieval and filtering work."""

    def encode(self, texts, query=False):
        out = np.zeros((len(texts), 256), dtype="float32")
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z]{3,}", t.lower()):
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
        out /= np.linalg.norm(out, axis=1, keepdims=True) + 1e-9
        return out


PDF_PAGES = [
    "Backpropagation\nBackpropagation applies the chain rule to compute the gradient of the loss with respect to each weight. "
    "Gradients flow from the output layer back to the input layer.",
    "Gradient Descent\nGradient descent updates every weight by subtracting the learning rate times the gradient. "
    "A learning rate that is too large makes the loss diverge.",
    "Overfitting\nOverfitting means the model memorises the training data. Dropout and weight decay are regularisers that reduce overfitting. " * 12,
]


def make_pdf(path):
    doc = pymupdf.open()
    for text in PDF_PAGES:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=9)
    doc.save(path)
    return path


def make_pptx(path):
    prs = pptx.Presentation()
    for title, body in [("Convolutional Networks", "Convolution layers slide small filters over the image to detect edges."),
                        ("Pooling", "Max pooling keeps the largest value in each window and shrinks the feature map.")]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    prs.save(path)
    return path


class FakeLLM:
    def __init__(self):
        self.prompts = []

    async def chat(self, messages, **kw):
        self.prompts.append(messages[-1]["content"])
        return "The chain rule computes the gradients [S1]."

    async def chat_json(self, messages, **kw):
        return {}


@pytest.fixture
def real(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "use_mocks", False)
    monkeypatch.setattr(s, "mock_retrieval", False)
    monkeypatch.setattr(s, "data_dir", str(tmp_path))
    monkeypatch.setattr(s, "min_score", 0.05)
    pipeline.set_embedder(HashEmbedder())
    store.documents.clear()
    llm = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    yield TestClient(app), llm, tmp_path
    app.dependency_overrides.clear()
    pipeline.set_embedder(None)
    store.documents.clear()


def test_extract_and_chunk_pdf(tmp_path):
    pages = pipeline.extract_pages(make_pdf(str(tmp_path / "l.pdf")))
    assert [p for p, _ in pages] == [1, 2, 3] and "chain rule" in pages[0][1]
    chunks = pipeline.chunk_pages("doc_x", "l.pdf", pages)
    long_page = [c for c in chunks if c.page == 3]
    s = get_settings()
    assert len(long_page) > 1 and all(len(c.text) <= s.chunk_size for c in chunks)
    # neighbouring chunks overlap so a sentence cut at a boundary is still found
    assert long_page[0].text[-40:].split()[-1] in long_page[1].text
    assert pipeline.detect_topics(chunks) == ["Backpropagation", "Gradient Descent", "Overfitting"]


def test_extract_pptx_uses_slide_titles(tmp_path):
    pages = pipeline.extract_pages(make_pptx(str(tmp_path / "s.pptx")))
    assert pages[0][1].startswith("Convolutional Networks")
    assert pipeline.detect_topics(pipeline.chunk_pages("d", "s.pptx", pages)) == ["Convolutional Networks", "Pooling"]


def test_empty_pdf_is_rejected(real, tmp_path):
    c, _, _ = real
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "blank.pdf"
    doc.save(str(path))
    r = c.post("/api/documents", files={"file": ("blank.pdf", path.read_bytes(), "application/pdf")})
    assert r.status_code == 400 and "OCR" in r.json()["error"]["message"]


def test_upload_ask_filter_delete_and_persist(real):
    c, llm, tmp = real
    pdf = make_pdf(str(tmp / "lecture.pdf"))
    ppt = make_pptx(str(tmp / "cnn.pptx"))
    d1 = c.post("/api/documents", files={"file": ("lecture.pdf", open(pdf, "rb"), "application/pdf")}).json()
    d2 = c.post("/api/documents", files={"file": ("cnn.pptx", open(ppt, "rb"), "application/octet-stream")}).json()
    assert d1["pages"] == 3 and d1["status"] == "ready" and "Backpropagation" in d1["topics"]
    assert d2["topics"] == ["Convolutional Networks", "Pooling"]

    body = c.post("/api/ask", json={"question": "How does the chain rule compute the gradient?"}).json()
    assert body["grounded"] and body["sources"][0]["page"] == 1 and body["sources"][0]["filename"] == "lecture.pdf"
    assert "[S1] (lecture.pdf, page 1)" in llm.prompts[-1]  # retrieved passage went into the prompt

    only_ppt = c.post("/api/ask", json={"question": "What does pooling do?", "document_ids": [d2["document_id"]]}).json()
    assert {s["document_id"] for s in only_ppt["sources"]} == {d2["document_id"]}

    # restart: index and library come back from DATA_DIR
    pipeline._index = None
    store.documents.clear()
    store.load()
    assert set(store.documents) == {d1["document_id"], d2["document_id"]}
    assert pipeline.retrieve("chain rule gradient", None, 3)[0].document_id == d1["document_id"]

    # delete removes the vectors too
    assert c.delete(f"/api/documents/{d1['document_id']}").status_code == 204
    assert {ch.document_id for ch in pipeline.get_index().chunks} == {d2["document_id"]}
    assert pipeline.retrieve("chain rule gradient", None, 10) == []
    assert pipeline.retrieve("max pooling window", None, 3)[0].page == 2


def test_progress_and_exams_survive_restart(real):
    store.record_result("persist", "Pooling", 1.0)
    store.save()
    store.progress.clear()
    store.load()
    assert store.progress["persist"]["Pooling"]["attempts"] == 1
