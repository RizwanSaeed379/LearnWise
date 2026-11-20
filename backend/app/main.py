"""LearnWise API.  Run:  uvicorn app.main:app --reload   then open http://localhost:8000/docs"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import ask, documents, exam, flashcards, notes, progress, quiz
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

for r in (documents, ask, notes, quiz, exam, flashcards, progress):
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
    reachable = None if settings.use_mocks else await LLMClient(settings).ping()
    return HealthResponse(status="ok", mock_mode=settings.use_mocks, llm_base_url=settings.llm_base_url, llm_model=settings.llm_model, llm_reachable=reachable)
