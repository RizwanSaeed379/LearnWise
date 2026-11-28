"""LearnWise API.  Run:  uvicorn app.main:app --reload   then open http://localhost:8000/docs"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import ask, documents, exam, flashcards, mindmap, notes, progress, quiz, speech
from app.schemas import HealthResponse
from app.services import mock, store
from app.services.llm import LLMClient, LLMError

settings = get_settings()
app = FastAPI(
    title="LearnWise API",
    version="0.1.0",
    description="Turns your lecture PDFs/slides into grounded answers, notes, quizzes, flashcards and graded mock exams.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (documents, ask, speech, notes, quiz, exam, flashcards, mindmap, progress):
    app.include_router(r.router)

if settings.use_mocks or settings.mock_retrieval:
    mock.seed()
else:
    store.load()  # library, progress and exams saved by the last run


# ---- one error shape for everything: {"error": {"code": ..., "message": ...}} ----
_CODES = {400: "bad_request", 404: "not_found", 409: "conflict", 413: "file_too_large", 415: "unsupported_file", 422: "validation_error", 501: "not_implemented", 502: "llm_error"}


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": _CODES.get(exc.status_code, "error"), "message": str(exc.detail)}})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": msg}})


@app.exception_handler(LLMError)
async def llm_error(_: Request, exc: LLMError):
    return JSONResponse(status_code=502, content={"error": {"code": "llm_error", "message": str(exc)}})


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
async def health():
    tts_mode = "ai" if settings.tts_base_url.strip() and not settings.use_mocks else "browser"
    if settings.use_mocks:
        return HealthResponse(status="ok", mock_mode=True, llm_base_url=settings.llm_base_url, llm_model=settings.llm_model)
    reachable = await LLMClient(settings).ping()
    mode = "remote" if settings.embedding_base_url.strip() else "local"
    emb_ok = None
    if mode == "remote":
        same = settings.embedding_base_url.rstrip("/") == settings.llm_base_url.rstrip("/")
        emb_ok = reachable if same else await LLMClient(settings.model_copy(update={"llm_base_url": settings.embedding_base_url, "llm_api_key": settings.embedding_api_key})).ping()
    return HealthResponse(status="ok", mock_mode=False, llm_base_url=settings.llm_base_url, llm_model=settings.llm_model, llm_reachable=reachable,
                          embedding_mode=mode, embedding_model=settings.embedding_model, embeddings_reachable=emb_ok, tts_mode=tts_mode)
