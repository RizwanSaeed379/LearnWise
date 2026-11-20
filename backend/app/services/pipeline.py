"""The real RAG pipeline. Used when USE_MOCKS=false.

    upload -> extract_pages -> chunk_pages -> index_chunks (embed + FAISS, saved to DATA_DIR/index)
    question -> retrieve (embed query, top-k cosine search, filter by document) -> format_context -> LLM

Extra packages:  pip install -r requirements-ml.txt
(PyMuPDF, python-pptx, sentence-transformers, faiss-cpu). If faiss is missing we fall back to
an exact numpy search, which gives the same results and is fast enough for a few thousand chunks.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass

import numpy as np

from app.config import get_settings
from app.schemas import SourceRef


class IngestError(ValueError):
    """The file could be read but gave nothing usable (e.g. a scanned PDF with no text layer)."""


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    filename: str
    page: int
    text: str


# ---------------------------------------------------------------- 1. extraction
def extract_pages(path: str) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for a PDF or PPTX file. Pages/slides without text are skipped.

    For slides, the title goes on the first line so detect_topics() can use it.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        pages = _extract_pdf(path)
    elif ext == ".pptx":
        pages = _extract_pptx(path)
    else:
        raise IngestError(f"Unsupported file type: {ext}")
    pages = [(n, t.strip()) for n, t in pages if t and t.strip()]
    if not pages:
        raise IngestError("No text found in this file. Scanned PDFs need OCR, which is not supported yet.")
    return pages


def _extract_pdf(path: str) -> list[tuple[int, str]]:
    try:
        import pymupdf
    except ImportError:  # older PyMuPDF
        import fitz as pymupdf
    try:
        with pymupdf.open(path) as doc:
            return [(i + 1, page.get_text("text")) for i, page in enumerate(doc)]
    except Exception as e:  # corrupt or encrypted file
        raise IngestError(f"Could not read this PDF ({e}).") from e


def _extract_pptx(path: str) -> list[tuple[int, str]]:
    from pptx import Presentation

    try:
        prs = Presentation(path)
    except Exception as e:
        raise IngestError(f"Could not read this PowerPoint file ({e}).") from e
    out = []
    for i, slide in enumerate(prs.slides):
        title_shape = slide.shapes.title
        title = title_shape.text_frame.text.strip() if title_shape is not None and title_shape.has_text_frame else ""
        lines = [title] if title else []
        for shape in slide.shapes:
            if shape is title_shape:
                continue
            if shape.has_text_frame:
                lines += [p.text for p in shape.text_frame.paragraphs if p.text.strip()]
            elif getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    lines.append(" | ".join(c.text for c in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append(f"Notes: {notes}")
        out.append((i + 1, "\n".join(lines)))
    return out


# ---------------------------------------------------------------- 2. chunking
_WS = re.compile(r"[ \t]+")


def _clean(text: str) -> str:
    text = text.replace("­", "")  # soft hyphens from PDFs
    text = re.sub(r"-\n(?=[a-z])", "", text)  # re-join words hyphenated across lines
    text = _WS.sub(" ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def _split(text: str, size: int, overlap: int) -> list[str]:
    """Windows of ~size characters with ~overlap shared, cut at a sentence or word boundary when possible."""
    if len(text) <= size:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind(". "), window.rfind("\n"), window.rfind("? "), window.rfind("! "))
            if cut < size * 0.5:
                cut = window.rfind(" ")
            if cut > size * 0.3:
                end = start + cut + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        nxt = end - overlap
        sp = text.find(" ", nxt)  # start the next chunk on a word
        start = sp + 1 if 0 <= sp < end else max(nxt, start + 1)
    return [p for p in parts if p]


def chunk_pages(document_id: str, filename: str, pages: list[tuple[int, str]]) -> list[Chunk]:
    """Split each page into overlapping chunks. Chunks never cross pages, so every chunk has one page number."""
    s = get_settings()
    chunks: list[Chunk] = []
    for page, text in pages:
        for piece in _split(_clean(text), s.chunk_size, s.chunk_overlap):
            if len(piece) < 20:  # page numbers, lone headers
                continue
            chunks.append(Chunk(f"{document_id}_c{len(chunks):04d}", document_id, filename, page, piece))
    if not chunks:
        raise IngestError("The file has too little text to index.")
    return chunks


# ---------------------------------------------------------------- 5. topics
_GENERIC = {
    "outline", "agenda", "contents", "table of contents", "overview", "summary", "introduction", "thank you",
    "thanks", "questions", "any questions", "q&a", "references", "bibliography", "acknowledgements", "the end",
}


def detect_topics(chunks: list[Chunk], max_topics: int = 12) -> list[str]:
    """Topics for the dropdowns: the title (first short line) of each page/slide, de-duplicated, generic titles removed."""
    first_by_page: dict[int, str] = {}
    for c in chunks:
        first_by_page.setdefault(c.page, c.text)
    seen, topics = set(), []
    for page in sorted(first_by_page):
        line = first_by_page[page].split("\n", 1)[0].strip(" :-•*#\t")
        line = re.sub(r"^\d+(\.\d+)*[.)]?\s+", "", line)  # "2.1 Gradient descent" -> "Gradient descent"
        key = line.lower()
        if not (3 <= len(line) <= 60) or len(line.split()) > 8 or key in _GENERIC or key in seen:
            continue
        if not re.search(r"[A-Za-z]{3}", line) or line.endswith((".", ",")):
            continue  # numbers, dates or a sentence rather than a heading
        seen.add(key)
        topics.append(line)
        if len(topics) >= max_topics:
            break
    return topics or ["General"]


# ---------------------------------------------------------------- 3. embeddings
class Embedder:
    """Sentence Transformers model, loaded once on first use. Vectors are L2-normalised (dot product = cosine)."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import, only when needed

            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    def encode(self, texts: list[str], query: bool = False) -> np.ndarray:
        if query and "bge" in self.model_name.lower():
            # BGE models retrieve better when queries carry this instruction (passages don't).
            texts = [f"Represent this sentence for searching relevant passages: {t}" for t in texts]
        vecs = self._load().encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype="float32")


_embedder: Embedder | None = None


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = Embedder(get_settings().embedding_model)
    return _embedder


def set_embedder(e) -> None:
    """Swap the embedder (tests use a tiny fake one)."""
    global _embedder
    _embedder = e


# ---------------------------------------------------------------- 4. vector index
class VectorIndex:
    """All chunks of all documents in one cosine-similarity index, saved under DATA_DIR/index/.

    vectors.npy holds the embeddings, chunks.json the matching metadata (same order).
    Deleting a document drops its rows and rebuilds the (small) FAISS index.
    """

    def __init__(self, folder: str):
        self.folder = folder
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None
        self._faiss = None
        self._lock = threading.Lock()
        self._load()

    # -- persistence
    @property
    def _vec_path(self):
        return os.path.join(self.folder, "vectors.npy")

    @property
    def _meta_path(self):
        return os.path.join(self.folder, "chunks.json")

    def _load(self):
        if os.path.exists(self._vec_path) and os.path.exists(self._meta_path):
            with open(self._meta_path, encoding="utf-8") as f:
                self.chunks = [Chunk(**c) for c in json.load(f)]
            self.vectors = np.load(self._vec_path)
            if len(self.chunks) != len(self.vectors):  # half-written save: start clean rather than mis-cite
                self.chunks, self.vectors = [], None
        self._rebuild()

    def _save(self):
        os.makedirs(self.folder, exist_ok=True)
        tmp_v, tmp_m = self._vec_path + ".tmp.npy", self._meta_path + ".tmp"
        np.save(tmp_v, self.vectors if self.vectors is not None else np.zeros((0, 1), "float32"))
        with open(tmp_m, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in self.chunks], f, ensure_ascii=False)
        os.replace(tmp_v, self._vec_path)
        os.replace(tmp_m, self._meta_path)

    def _rebuild(self):
        self._faiss = None
        if self.vectors is None or not len(self.vectors):
            return
        try:
            import faiss
        except ImportError:
            return  # numpy fallback in search()
        idx = faiss.IndexFlatIP(self.vectors.shape[1])
        idx.add(self.vectors)
        self._faiss = idx

    # -- operations
    def add(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        with self._lock:
            self.chunks += chunks
            self.vectors = vectors if self.vectors is None or not len(self.vectors) else np.vstack([self.vectors, vectors])
            self._rebuild()
            self._save()

    def delete_document(self, document_id: str) -> int:
        with self._lock:
            keep = [i for i, c in enumerate(self.chunks) if c.document_id != document_id]
            removed = len(self.chunks) - len(keep)
            if removed:
                self.chunks = [self.chunks[i] for i in keep]
                self.vectors = self.vectors[keep] if keep else None
                self._rebuild()
                self._save()
            return removed

    def search(self, qvec: np.ndarray, k: int, document_ids: list[str] | None = None) -> list[tuple[Chunk, float]]:
        if self.vectors is None or not len(self.vectors):
            return []
        allowed = set(document_ids) if document_ids else None
        n = len(self.chunks)
        # When filtering, over-fetch so enough hits survive the filter.
        fetch = n if allowed else min(k, n)
        if self._faiss is not None:
            scores, ids = self._faiss.search(qvec.reshape(1, -1), fetch)
            hits = zip(ids[0], scores[0])
        else:
            sims = self.vectors @ qvec.reshape(-1)
            order = np.argsort(-sims)[:fetch]
            hits = ((i, sims[i]) for i in order)
        out = []
        for i, score in hits:
            if i < 0:
                continue
            c = self.chunks[int(i)]
            if allowed and c.document_id not in allowed:
                continue
            out.append((c, float(score)))
            if len(out) >= k:
                break
        return out


_index: VectorIndex | None = None


def get_index() -> VectorIndex:
    global _index
    folder = os.path.join(get_settings().data_dir, "index")
    if _index is None or _index.folder != folder:
        _index = VectorIndex(folder)
    return _index


def index_chunks(chunks: list[Chunk]) -> None:
    """Embed chunks and add them to the FAISS index (saved to disk)."""
    vecs = get_embedder().encode([c.text for c in chunks])
    get_index().add(chunks, vecs)


def delete_document(document_id: str) -> int:
    """Remove a document's vectors. Returns how many chunks were removed."""
    return get_index().delete_document(document_id)


# ---------------------------------------------------------------- retrieval
def retrieve(query: str, document_ids: list[str] | None, top_k: int) -> list[SourceRef]:
    """Embed the query, search the index, keep only the given documents, return the best passages."""
    index = get_index()
    if not index.chunks:
        return []
    q = get_embedder().encode([query], query=True)[0]
    min_score = get_settings().min_score
    return [
        SourceRef(document_id=c.document_id, filename=c.filename, page=c.page, chunk_id=c.chunk_id, snippet=c.text, score=round(max(0.0, min(1.0, s)), 3))
        for c, s in index.search(q, top_k, document_ids)
        if s >= min_score
    ]


def format_context(sources: list[SourceRef]) -> str:
    """Turn retrieved passages into the CONTEXT block of a prompt, labelled so the LLM can cite them."""
    return "\n\n".join(f"[S{i + 1}] ({s.filename}, page {s.page})\n{s.snippet}" for i, s in enumerate(sources))
