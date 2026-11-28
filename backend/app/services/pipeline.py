"""The real RAG pipeline. Used when USE_MOCKS=false.

    upload -> extract_pages -> chunk_pages -> index_chunks (embed + FAISS, saved to DATA_DIR/index)
    question -> retrieve -> build_context (dedupe, merge neighbours, token budget) -> LLM
        retrieve: dense cosine search (FAISS) + BM25 keyword search over the same chunks, fused with
        Reciprocal Rank Fusion, optionally re-ranked by a cross-encoder, filtered by document.

Extra packages:  pip install -r requirements-ml.txt   (PyMuPDF, python-pptx, faiss-cpu, numpy)
Embeddings run either on Kaggle (EMBEDDING_BASE_URL set, nothing else to install) or on this
computer (pip install -r requirements-local-embeddings.txt for sentence-transformers).
If faiss is missing we fall back to an exact numpy search, which gives the same results and is
fast enough for a few thousand chunks.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import Counter
import threading
from dataclasses import asdict, dataclass

import numpy as np

from app.config import get_settings
from app.schemas import SourceRef
from app.services.llm import LLMError
from app.services.text import words

log = logging.getLogger("learnwise.pipeline")


class IngestError(ValueError):
    """The file could be read but gave nothing usable (e.g. a scanned PDF with no text layer)."""


class EmbeddingError(LLMError):
    """The remote embedding server failed (shown to the user as a 502 llm_error)."""


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
    "learning objectives", "learning outcomes", "objectives", "review questions", "practice questions", "exercises",
    "announcements", "readings", "reading", "administrivia", "an example", "example", "examples",
}
_NUMBERED = re.compile(r"^\d+(\.\d+)*[.)]?\s+[A-Z]")           # "3.1 Light-dependent reactions"
_SECTION_NO = re.compile(r"^\d+(\.\d+)*[.)]?$")
_PAGE_NO = re.compile(r"^(page|slide)?\s*\d+(\s*(/|of)\s*\d+)?$", re.I)  # "Page 2", "3 / 12", "7"


def _as_heading(line: str) -> str | None:
    line = line.strip(" :-•*#\t")
    line = re.sub(r"^\d+(\.\d+)*[.)]?\s+", "", line)  # "2.1 Gradient descent" -> "Gradient descent"
    if not (3 <= len(line) <= 60) or len(line.split()) > 8 or line.lower() in _GENERIC:
        return None
    if not re.search(r"[A-Za-z]{3}", line) or line.endswith((".", ",")):
        return None  # numbers, dates or a sentence rather than a heading
    if not (line[0].isupper() or line[0].isdigit()) or line.count("(") != line.count(")"):
        return None  # code ("for t1 in outer", "(hasNext)") or a heading cut off mid-bracket
    return line


def detect_topics(chunks: list[Chunk], max_topics: int = 12) -> list[str]:
    """Topics for the dropdowns: the title (first short line) of each page/slide plus numbered section headings
    ("3.1 Light-dependent reactions") inside it, de-duplicated, generic titles removed.

    A line that appears on at least half the pages of a 3+ page document is a running header or footer
    (usually the document title), not a page title, so it is skipped, as are page numbers."""
    text_by_page: dict[int, list[str]] = {}
    for c in chunks:
        text_by_page.setdefault(c.page, []).append(c.text)
    lines_by_page = {p: [l.strip() for l in "\n".join(t).split("\n") if l.strip()] for p, t in text_by_page.items()}
    counts = Counter(l.lower() for lines in lines_by_page.values() for l in set(lines))
    n_pages = len(lines_by_page)
    repeated = {l for l, n in counts.items() if n_pages >= 3 and n >= max(2, n_pages / 2)}

    seen, topics = set(), []
    for page in sorted(lines_by_page):
        raw = lines_by_page[page]
        # a section number alone on its line, with the heading on the next line ("2" then "Readings")
        split_numbered = [l for prev, l in zip(raw, raw[1:]) if _SECTION_NO.match(prev) and l[:1].isupper()]
        lines = [l for l in raw if l.lower() not in repeated and not _PAGE_NO.match(l)]
        numbered = [l for l in lines[1:] if _NUMBERED.match(l) or l in split_numbered]
        for line in lines[:1] + numbered:
            heading = _as_heading(line)
            if heading and heading.lower() not in seen:
                seen.add(heading.lower())
                topics.append(heading)
                if len(topics) >= max_topics:
                    return topics
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


class RemoteEmbedder(Embedder):
    """Same model, computed on the Kaggle GPU through the OpenAI-compatible POST {base}/embeddings.

    Lets an 8 GB laptop skip installing PyTorch. Vectors match the local model, so you can switch
    between local and remote without rebuilding the index.
    """

    def __init__(self, model_name: str, base_url: str, api_key: str, timeout: float = 120):
        super().__init__(model_name)
        self.base_url, self.api_key, self.timeout = base_url.rstrip("/"), api_key, timeout

    def encode(self, texts: list[str], query: bool = False) -> np.ndarray:
        import httpx

        if query and "bge" in self.model_name.lower():
            texts = [f"Represent this sentence for searching relevant passages: {t}" for t in texts]
        headers = {"Authorization": f"Bearer {self.api_key}", "ngrok-skip-browser-warning": "true"}
        out = []
        try:
            with httpx.Client(timeout=self.timeout) as client:
                for i in range(0, len(texts), 64):
                    r = client.post(f"{self.base_url}/embeddings", json={"model": self.model_name, "input": texts[i : i + 64]}, headers=headers)
                    r.raise_for_status()
                    out += [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise EmbeddingError(f"Embedding request to {self.base_url} failed: {e}") from e
        vecs = np.asarray(out, dtype="float32")
        return vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12)


_embedder: Embedder | None = None


def get_embedder():
    global _embedder
    if _embedder is None:
        s = get_settings()
        if s.embedding_base_url.strip():
            _embedder = RemoteEmbedder(s.embedding_model, s.embedding_base_url, s.embedding_api_key, s.llm_timeout_seconds)
        else:
            _embedder = Embedder(s.embedding_model)
    return _embedder


def missing_package_message(e: ImportError) -> str:
    if e.name == "sentence_transformers":
        return ("Embeddings need either the Kaggle server (set EMBEDDING_BASE_URL in .env) or a local model "
                "(pip install -r requirements-local-embeddings.txt).")
    return f"Missing package ({e.name}). Run: pip install -r requirements-ml.txt"


def embedding_mode() -> str:
    return "remote" if get_settings().embedding_base_url.strip() else "local"


def set_embedder(e) -> None:
    """Swap the embedder (tests use a tiny fake one)."""
    global _embedder
    _embedder = e


# ---------------------------------------------------------------- 4a. keyword index
class BM25:
    """Okapi BM25 over chunk texts (k1=1.5, b=0.75). Catches exact terms (names, formulas, acronyms)
    that a small embedding model can miss. Built in memory from the stored chunk texts, so nothing new is saved."""

    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [words(t) for t in texts]
        self.lengths = np.array([len(d) for d in self.docs], dtype="float32")
        self.avgdl = float(self.lengths.mean()) if len(self.docs) else 0.0
        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for d in self.docs:
            counts: dict[str, int] = {}
            for w in d:
                counts[w] = counts.get(w, 0) + 1
            self.tf.append(counts)
            for w in counts:
                df[w] = df.get(w, 0) + 1
        n = len(self.docs)
        # BM25+ style idf that never goes negative (common words just score ~0)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(len(self.docs), dtype="float32")
        if not self.docs or self.avgdl == 0:
            return out
        for w in set(words(query)):
            idf = self.idf.get(w)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(w)
                if f:
                    norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avgdl)
                    out[i] += idf * f * (self.k1 + 1) / (f + norm)
        return out


def rrf(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1 / (k + rank). Best first."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, i in enumerate(ranking, start=1):
            fused[i] = fused.get(i, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda x: (-x[1], x[0]))


# ---------------------------------------------------------------- 4b. re-ranker
class CrossEncoderReranker:
    """Scores (query, passage) pairs jointly; more accurate than the bi-encoder but slower, so it only sees
    the fused top candidates. Needs sentence-transformers (requirements-local-embeddings.txt)."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def score(self, query: str, texts: list[str]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, device="cpu")
        return [float(x) for x in self._model.predict([(query, t) for t in texts], show_progress_bar=False)]


_reranker = None
_reranker_name: str | None = None
_reranker_failed: str | None = None  # model that failed to load: don't retry it on every question


def get_reranker():
    """The configured re-ranker, or None when RERANK_MODEL is empty (or it failed to load)."""
    global _reranker, _reranker_name
    name = get_settings().rerank_model.strip()
    if _reranker_name == "<custom>":
        return _reranker
    if not name or name == _reranker_failed:
        return None
    if _reranker is None or _reranker_name != name:
        _reranker, _reranker_name = CrossEncoderReranker(name), name
    return _reranker


def set_reranker(r) -> None:
    """Swap the re-ranker (tests use a fake one). None restores the configured one."""
    global _reranker, _reranker_name, _reranker_failed
    _reranker, _reranker_name, _reranker_failed = r, ("<custom>" if r is not None else None), None


# ---------------------------------------------------------------- 4c. vector index
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
        self._bm25: BM25 | None = None
        self._lock = threading.Lock()
        self._load()

    # -- persistence
    @property
    def _vec_path(self):
        return os.path.join(self.folder, "vectors.npy")

    @property
    def _meta_path(self):
        return os.path.join(self.folder, "chunks.json")

    @property
    def _model_path(self):
        return os.path.join(self.folder, "model.txt")

    def _load(self):
        if os.path.exists(self._vec_path) and os.path.exists(self._meta_path):
            with open(self._meta_path, encoding="utf-8") as f:
                self.chunks = [Chunk(**c) for c in json.load(f)]
            self.vectors = np.load(self._vec_path)
            if len(self.chunks) != len(self.vectors):  # half-written save: start clean rather than mis-cite
                self.chunks, self.vectors = [], None
        saved_model = open(self._model_path, encoding="utf-8").read().strip() if os.path.exists(self._model_path) else None
        self.model_changed = bool(self.chunks) and saved_model not in (None, get_settings().embedding_model)
        self._rebuild()

    def reembed_if_model_changed(self) -> None:
        """EMBEDDING_MODEL changed since the index was built: old vectors are incomparable, so re-embed the stored texts."""
        if self.model_changed:
            with self._lock:
                self.vectors = get_embedder().encode([c.text for c in self.chunks])
                self.model_changed = False
                self._rebuild()
                self._save()

    def _save(self):
        os.makedirs(self.folder, exist_ok=True)
        tmp_v, tmp_m = self._vec_path + ".tmp.npy", self._meta_path + ".tmp"
        np.save(tmp_v, self.vectors if self.vectors is not None else np.zeros((0, 1), "float32"))
        with open(tmp_m, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in self.chunks], f, ensure_ascii=False)
        os.replace(tmp_v, self._vec_path)
        os.replace(tmp_m, self._meta_path)
        with open(self._model_path, "w", encoding="utf-8") as f:
            f.write(get_settings().embedding_model)

    def _rebuild(self):
        self._faiss = None
        self._bm25 = None  # rebuilt from the chunk texts on the next keyword search
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


    def bm25(self) -> BM25:
        with self._lock:
            if self._bm25 is None or len(self._bm25.docs) != len(self.chunks):
                self._bm25 = BM25([c.text for c in self.chunks])
            return self._bm25

    def hybrid_candidates(self, query: str, qvec: np.ndarray, pool: int, document_ids: list[str] | None = None,
                          rrf_k: int = 60, use_bm25: bool = True) -> list[tuple[Chunk, float, float]]:
        """Up to `pool` chunks ordered by RRF of the dense and BM25 rankings: [(chunk, cosine, rrf_score)].

        Both rankings are computed over the allowed documents only. The cosine is returned for every
        candidate (also BM25-only ones) so the caller can apply MIN_SCORE the same way as before.
        """
        if self.vectors is None or not len(self.vectors):
            return []
        allowed = set(document_ids) if document_ids else None
        ok = np.array([allowed is None or c.document_id in allowed for c in self.chunks])
        if not ok.any():
            return []
        sims = self.vectors @ qvec.reshape(-1)  # exact cosine, same numbers as IndexFlatIP
        dense = [int(i) for i in np.argsort(-sims, kind="stable") if ok[i]][:pool]
        rankings = [dense]
        if use_bm25:
            kw = self.bm25().scores(query)
            rankings.append([int(i) for i in np.argsort(-kw, kind="stable") if ok[i] and kw[i] > 0][:pool])
        return [(self.chunks[i], float(sims[i]), sc) for i, sc in rrf(rankings, rrf_k)[:pool]]


_index: VectorIndex | None = None


def get_index() -> VectorIndex:
    global _index
    folder = os.path.join(get_settings().data_dir, "index")
    if _index is None or _index.folder != folder:
        _index = VectorIndex(folder)
    _index.reembed_if_model_changed()
    return _index


def index_chunks(chunks: list[Chunk]) -> None:
    """Embed chunks and add them to the FAISS index (saved to disk)."""
    vecs = get_embedder().encode([c.text for c in chunks])
    get_index().add(chunks, vecs)


def delete_document(document_id: str) -> int:
    """Remove a document's vectors. Returns how many chunks were removed."""
    return get_index().delete_document(document_id)


# ---------------------------------------------------------------- retrieval
def _ref(c: Chunk, cosine: float) -> SourceRef:
    return SourceRef(document_id=c.document_id, filename=c.filename, page=c.page, chunk_id=c.chunk_id, snippet=c.text, score=round(max(0.0, min(1.0, cosine)), 3))


def retrieve(query: str, document_ids: list[str] | None, top_k: int) -> list[SourceRef]:
    """Return the best passages for a query from the given documents (all documents when None).

    HYBRID_RETRIEVAL=true: dense + BM25 rankings fused with RRF; RERANK_MODEL set: the fused top
    RERANK_CANDIDATES are re-ordered by a cross-encoder (if it can't load or fails, the fused order is kept).
    HYBRID_RETRIEVAL=false: plain dense top-k, as before.
    In every mode a passage needs cosine >= MIN_SCORE, so out-of-scope questions still find nothing.
    SourceRef.score stays the cosine similarity (0-1).
    """
    index = get_index()
    if not index.chunks:
        return []
    s = get_settings()
    q = get_embedder().encode([query], query=True)[0]
    if not s.hybrid_retrieval:
        return [_ref(c, sc) for c, sc in index.search(q, top_k, document_ids) if sc >= s.min_score]

    pool = max(top_k, s.rerank_candidates)
    cands = [(c, cos) for c, cos, _ in index.hybrid_candidates(query, q, pool, document_ids, s.rrf_k, use_bm25=True) if cos >= s.min_score]
    reranker = get_reranker()
    if reranker is not None and len(cands) > 1:
        try:
            scores = reranker.score(query, [c.text for c, _ in cands])
            order = sorted(range(len(cands)), key=lambda i: -scores[i])  # stable: ties keep fused order
            cands = [cands[i] for i in order]
        except Exception as e:  # missing package, download failure, bad model name: keep the fused order
            global _reranker_failed
            if _reranker_name != "<custom>":
                _reranker_failed = s.rerank_model.strip()
            log.warning("re-ranker failed, using fused order: %s", e)
    return [_ref(c, cos) for c, cos in cands[:top_k]]


DOC_OPEN, DOC_CLOSE = "<documents>", "</documents>"


def _defang(text: str) -> str:
    """Stop a document from closing the <documents> block itself (prompt injection through uploaded files)."""
    return re.sub(r"</?\s*documents\s*>", "[documents tag removed]", text, flags=re.I)


def _render(sources: list[SourceRef]) -> str:
    """The CONTEXT block: passages labelled [S1], [S2] ... inside <documents> ... </documents>.
    The system prompt says text inside the block is material to read, never instructions to follow."""
    body = "\n\n".join(f"[S{i + 1}] ({s.filename}, page {s.page})\n{_defang(s.snippet)}" for i, s in enumerate(sources))
    return f"{DOC_OPEN}\n{body}\n{DOC_CLOSE}"


def estimate_tokens(text: str) -> int:
    """~4 characters per token for English (no tokenizer download needed). Errs a little high on purpose."""
    return len(text) // 4 + 1


_NORM = re.compile(r"\s+")
_CHUNK_NO = re.compile(r"_c(\d+)$")


def _norm(t: str) -> str:
    return _NORM.sub(" ", t).strip().lower()


def _join_overlap(a: str, b: str, min_overlap: int = 20) -> str:
    """a + b without the text they share (chunks overlap by CHUNK_OVERLAP characters)."""
    if _norm(b) in _norm(a):
        return a
    for k in range(min(len(a), len(b)), min_overlap - 1, -1):
        if a.endswith(b[:k]):
            return a + b[k:]
    return a.rstrip() + " " + b.lstrip()


def _merge_run(run: list[tuple[int, SourceRef]]) -> tuple[int, SourceRef]:
    text = run[0][1].snippet
    for _, s in run[1:]:
        text = _join_overlap(text, s.snippet)
    rank = min(r for r, _ in run)
    best = max(s.score for _, s in run)
    first = run[0][1]
    return rank, first.model_copy(update={"snippet": text, "chunk_id": "+".join(s.chunk_id for _, s in run), "score": best})


def build_context(sources: list[SourceRef], budget_tokens: int | None = None) -> tuple[str, list[SourceRef]]:
    """Build the prompt's CONTEXT block from retrieved passages. Returns (context, the passages used, in label order).

    `sources` must be best-first, as retrieve() returns them (fused/re-ranked order, which is not always
    the cosine order of SourceRef.score).
    1. dedupe: a passage whose text equals or is contained in a better-ranked one is dropped
       (a longer passage that contains better-ranked ones replaces them and takes their rank);
    2. merge: passages that are neighbouring chunks of the same page (chunk n and n+1) become one passage,
       with the overlapping text written once; it takes the best rank and score of its parts;
    3. budget: passages are added best-first until the next one would pass budget_tokens
       (CONTEXT_BUDGET_TOKENS by default). The best passage is always kept, cut to fit if needed.
    The returned list is what [S1], [S2] ... refer to, so callers must map labels with it.
    """
    budget = get_settings().context_budget_tokens if budget_tokens is None else budget_tokens
    kept: list[tuple[int, SourceRef]] = []
    for rank, s in enumerate(sources):
        n = _norm(s.snippet)
        if not n or any(n in _norm(k.snippet) for _, k in kept):
            continue
        inside = [(r, k) for r, k in kept if _norm(k.snippet) in n]
        if inside:
            rank = min(r for r, _ in inside)
            s = s.model_copy(update={"score": max([s.score] + [k.score for _, k in inside])})
        kept = [x for x in kept if x not in inside] + [(rank, s)]

    groups: dict[tuple[str, int], list[tuple[int, SourceRef]]] = {}
    for r, s in kept:
        groups.setdefault((s.document_id, s.page), []).append((r, s))
    units: list[tuple[int, SourceRef]] = []
    for group in groups.values():
        units += [(r, s) for r, s in group if not _CHUNK_NO.search(s.chunk_id)]
        numbered = sorted(((int(_CHUNK_NO.search(s.chunk_id).group(1)), r, s) for r, s in group if _CHUNK_NO.search(s.chunk_id)), key=lambda x: x[0])
        run: list[tuple[int, SourceRef]] = []
        for i, (no, r, s) in enumerate(numbered):
            if run and no != numbered[i - 1][0] + 1:
                units.append(_merge_run(run))
                run = []
            run.append((r, s))
        if run:
            units.append(_merge_run(run))
    units.sort(key=lambda x: x[0])

    used: list[SourceRef] = []
    spent = estimate_tokens(DOC_OPEN + DOC_CLOSE)
    for _, s in units:
        cost = estimate_tokens(f"[S{len(used) + 1}] ({s.filename}, page {s.page})\n{s.snippet}\n\n")
        if spent + cost > budget:
            if not used:  # always give the model the best passage, cut at a word to fit
                room = max(0, (budget - spent - estimate_tokens(f"[S1] ({s.filename}, page {s.page})\n"))) * 4
                cut = s.snippet[:room].rsplit(" ", 1)[0] if room < len(s.snippet) else s.snippet
                used.append(s.model_copy(update={"snippet": cut}))
            break
        used.append(s)
        spent += cost
    return _render(used), used
