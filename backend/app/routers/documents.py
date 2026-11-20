import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

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
        pages = pipeline.extract_pages(path)
        chunks = pipeline.chunk_pages(doc_id, name, pages)
        pipeline.index_chunks(chunks)
        topics = pipeline.detect_topics(chunks)
    except NotImplementedError as e:
        raise HTTPException(501, detail=f"Ingestion not implemented yet ({e}). Set USE_MOCKS=true.")
    doc = DocumentInfo(document_id=doc_id, filename=name, pages=len(pages), chunks=len(chunks), topics=topics, status="ready", uploaded_at=store.now())
    store.documents[doc_id] = doc
    return doc


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
    # TODO(Rizwan): also remove its vectors from the FAISS index
    if store.documents.pop(document_id, None) is None:
        raise HTTPException(404, detail="Document not found.")
