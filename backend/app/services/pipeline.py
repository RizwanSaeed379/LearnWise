"""The real RAG pipeline (owner: Rizwan). Used when USE_MOCKS=false.

Install the extra packages first:  pip install -r requirements-ml.txt

Suggested order of work:
  1. extract_pages()   PyMuPDF:  doc = fitz.open(path); page.get_text()
  2. chunk_pages()     ~800 characters, 150 overlap, keep page number on every chunk
  3. Embedder          SentenceTransformer(settings.embedding_model), normalize_embeddings=True
  4. VectorIndex       faiss.IndexFlatIP (inner product on normalized vectors = cosine);
                       save index + chunk metadata (JSON) under DATA_DIR
  5. retrieve()        embed the question, search top_k, return SourceRef list
  6. Routers already call these functions; fill them in and flip USE_MOCKS=false.
"""
from dataclasses import dataclass

from app.schemas import SourceRef


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    filename: str
    page: int
    text: str


def extract_pages(path: str) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for a PDF or PPTX file."""
    raise NotImplementedError("TODO(Rizwan): PyMuPDF for PDF, python-pptx for PPTX")


def chunk_pages(document_id: str, filename: str, pages: list[tuple[int, str]]) -> list[Chunk]:
    """Split page text into overlapping chunks, keeping the page number."""
    raise NotImplementedError("TODO(Rizwan)")


def index_chunks(chunks: list[Chunk]) -> None:
    """Embed chunks and add them to the FAISS index (and save to disk)."""
    raise NotImplementedError("TODO(Rizwan)")


def detect_topics(chunks: list[Chunk]) -> list[str]:
    """Topic list for the dropdowns. Start simple: slide titles / first line of each page, or ask the LLM."""
    raise NotImplementedError("TODO(Rizwan)")


def retrieve(query: str, document_ids: list[str] | None, top_k: int) -> list[SourceRef]:
    """Embed the query, search FAISS, filter by document_ids, return the best passages."""
    raise NotImplementedError("TODO(Rizwan)")


def format_context(sources: list[SourceRef]) -> str:
    """Turn retrieved passages into the CONTEXT block of a prompt, labelled so the LLM can cite them."""
    return "\n\n".join(f"[S{i + 1}] ({s.filename}, page {s.page})\n{s.snippet}" for i, s in enumerate(sources))
