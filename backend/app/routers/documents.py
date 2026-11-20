import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.config import get_settings
from app.schemas import DocumentInfo, DocumentList
from app.services import mock, pipeline, store

router = APIRouter(prefix="/api/documents", tags=["documents"])
ALLOWED = (".pdf", ".pptx")
MAX_MB = 25


@router.post("", response_model=DocumentInfo, status_code=201, summary="Upload a PDF or PPTX")
async def upload(file: UploadFile = File(...)):
    name = file.filename or "upload"
    if not name.lower().endswith(ALLOWED):
        raise HTTPException(415, detail=f"Only {', '.join(ALLOWED)} files are supported.")
    data = await file.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, detail=f"File is larger than {MAX_MB} MB.")

    s = get_settings()
    if s.use_mocks or s.mock_retrieval:
        doc = mock.fake_document(name)
        store.documents[doc.document_id] = doc
        return doc

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    os.makedirs(os.path.join(s.data_dir, "uploads"), exist_ok=True)
    path = os.path.join(s.data_dir, "uploads", f"{doc_id}_{os.path.basename(name)}")
    with open(path, "wb") as f:
        f.write(data)
    try:
        # CPU-heavy (parsing + embeddings): run off the event loop so other requests keep working.
        pages, chunks, topics = await run_in_threadpool(_ingest, path, doc_id, name)
    except pipeline.IngestError as e:
        os.remove(path)
        raise HTTPException(400, detail=str(e))
    except ImportError as e:
        os.remove(path)
        raise HTTPException(501, detail=f"Missing ML package ({e.name}). Run: pip install -r requirements-ml.txt")
    doc = DocumentInfo(document_id=doc_id, filename=name, pages=len(pages), chunks=len(chunks), topics=topics, status="ready", uploaded_at=store.now())
    store.documents[doc_id] = doc
    store.save()
    return doc


def _ingest(path: str, doc_id: str, name: str):
    pages = pipeline.extract_pages(path)
    chunks = pipeline.chunk_pages(doc_id, name, pages)
    pipeline.index_chunks(chunks)
    return pages, chunks, pipeline.detect_topics(chunks)


@router.get("", response_model=DocumentList, summary="List uploaded documents")
async def list_documents():
    return DocumentList(documents=list(store.documents.values()))


@router.get("/{document_id}", response_model=DocumentInfo)
async def get_document(document_id: str):
    if document_id not in store.documents:
        raise HTTPException(404, detail="Document not found.")
    return store.documents[document_id]


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str):
    if store.documents.pop(document_id, None) is None:
        raise HTTPException(404, detail="Document not found.")
    s = get_settings()
    if not (s.use_mocks or s.mock_retrieval):
        pipeline.delete_document(document_id)  # drop its vectors from the index
        folder = os.path.join(s.data_dir, "uploads")
        for f in os.listdir(folder) if os.path.isdir(folder) else []:
            if f.startswith(f"{document_id}_"):
                os.remove(os.path.join(folder, f))
    store.save()
