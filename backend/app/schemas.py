"""Request and response models. This file IS the API contract in code form.

If you change a field here, update docs/API_CONTRACT.md and regenerate
docs/openapi.json with `python scripts/export_openapi.py`.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Difficulty = Literal["easy", "medium", "hard"]
NoteStyle = Literal["concise", "detailed", "exam"]
QuestionType = Literal["mcq", "short"]


# ---------- shared ----------
class SourceRef(BaseModel):
    """A passage from an uploaded document that supports the answer."""
    document_id: str
    filename: str
    page: int = Field(description="1-based page (or slide) number")
    chunk_id: str = Field(description="Chunk id; merged passages join their chunk ids with '+'")
    snippet: str = Field(description="The retrieved passage text: one chunk (up to ~800 characters), or neighbouring "
                         "chunks of the same page merged into one passage")
    score: float = Field(description="Similarity score, higher is more relevant (0-1)")


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: Literal["ok"]
    mock_mode: bool
    llm_base_url: str
    llm_model: str
    llm_reachable: Optional[bool] = Field(None, description="null when mock mode skips the check")
    embedding_mode: Literal["mock", "local", "remote"] = Field("mock", description="where embeddings are computed")
    embedding_model: Optional[str] = None
    embeddings_reachable: Optional[bool] = Field(None, description="remote mode only; null otherwise")


# ---------- documents ----------
class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    pages: int
    chunks: int
    topics: list[str]
    status: Literal["processing", "ready", "failed"]
    uploaded_at: datetime


class DocumentList(BaseModel):
    documents: list[DocumentInfo]


# ---------- ask (RAG) ----------
class AskRequest(BaseModel):
    question: str = Field(min_length=3, examples=["What is backpropagation?"])
    document_ids: Optional[list[str]] = Field(None, description="Limit search to these documents; null = all")
    top_k: int = Field(5, ge=1, le=20)


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceRef]
    grounded: bool = Field(description="false when no relevant passage was found and the model says so, or when the "
                           "answer failed the citation/support check against its passages (VERIFY_ANSWERS)")


# ---------- notes ----------
class NotesRequest(BaseModel):
    topic: str = Field(min_length=2, examples=["Gradient descent"])
    style: NoteStyle = "concise"
    document_ids: Optional[list[str]] = None


class NoteSection(BaseModel):
    heading: str
    content: str
    bullets: list[str] = []
    key_terms: list[str] = []


class NotesResponse(BaseModel):
    title: str
    style: NoteStyle
    sections: list[NoteSection]
    sources: list[SourceRef]


# ---------- quiz ----------
class QuizRequest(BaseModel):
    topic: str = Field(min_length=2)
    difficulty: Difficulty = "medium"
    num_mcq: int = Field(4, ge=0, le=20)
    num_short: int = Field(1, ge=0, le=10)
    document_ids: Optional[list[str]] = None
    user_id: str = "demo"


class QuizQuestion(BaseModel):
    question_id: str
    type: QuestionType
    question: str
    options: Optional[list[str]] = Field(None, description="Exactly 4 options for mcq, null for short")
    topic: str
    difficulty: Difficulty
    source: Optional[SourceRef] = None


class QuizResponse(BaseModel):
    """Answers are NOT included, so the frontend cannot leak them. Submit to get them."""
    quiz_id: str
    topic: str
    difficulty: Difficulty
    questions: list[QuizQuestion]


class QuizAnswer(BaseModel):
    question_id: str
    answer: str = Field(description="For mcq: the option index as a string ('0'-'3'). For short: free text.")


class QuizSubmitRequest(BaseModel):
    user_id: str = "demo"
    answers: list[QuizAnswer]


class QuestionResult(BaseModel):
    question_id: str
    correct: bool
    score: float = Field(ge=0, le=1, description="1 for correct mcq; partial credit possible for short answers")
    your_answer: str
    correct_answer: str
    explanation: str
    topic: str


class QuizSubmitResponse(BaseModel):
    quiz_id: str
    score: float
    total: int
    percentage: float
    results: list[QuestionResult]
    weak_topics: list[str]


# ---------- flashcards ----------
class FlashcardsRequest(BaseModel):
    topic: str = Field(min_length=2)
    count: int = Field(8, ge=1, le=30)
    document_ids: Optional[list[str]] = None


class Flashcard(BaseModel):
    card_id: str
    front: str
    back: str
    topic: str
    source: Optional[SourceRef] = None


class FlashcardsResponse(BaseModel):
    topic: str
    cards: list[Flashcard]


# ---------- progress / adaptive practice ----------
class TopicProgress(BaseModel):
    topic: str
    attempts: int
    correct: float
    mastery: float = Field(ge=0, le=1, description="correct / attempts, smoothed")
    last_practiced: Optional[datetime] = None


class QuizHistoryItem(BaseModel):
    quiz_id: str
    topic: str
    difficulty: Difficulty
    percentage: float
    taken_at: datetime


class ProgressResponse(BaseModel):
    user_id: str
    topics: list[TopicProgress]
    weak_topics: list[str] = Field(description="Topics with mastery below 0.6, weakest first")
    recent_quizzes: list[QuizHistoryItem]


class PracticeRequest(BaseModel):
    user_id: str = "demo"
    max_topics: int = Field(2, ge=1, le=5)
    questions_per_topic: int = Field(3, ge=1, le=10)
    document_ids: Optional[list[str]] = None


class PracticeTopic(BaseModel):
    topic: str
    mastery: float
    reason: str = Field(description="Why this topic was picked, shown to the student")
    explanation: str = Field(description="A fresh, simpler explanation of the topic")


class PracticeResponse(BaseModel):
    user_id: str
    selected: list[PracticeTopic]
    quiz: QuizResponse


# ---------- graded mock exam ----------
ExamDifficulty = Literal["adaptive", "easy", "medium", "hard"]
Grade = Literal["A", "B", "C", "D", "F"]


class ExamRequest(BaseModel):
    user_id: str = "demo"
    topics: Optional[list[str]] = Field(None, description="Topics to cover; null = personalised pick (weak topics first, then unseen document topics)")
    num_mcq: int = Field(8, ge=0, le=40)
    num_short: int = Field(3, ge=0, le=15)
    difficulty: ExamDifficulty = Field("adaptive", description="'adaptive' sets difficulty per topic from the student's mastery")
    time_limit_minutes: int = Field(30, ge=5, le=180)
    max_topics: int = Field(4, ge=1, le=8)
    document_ids: Optional[list[str]] = None


class ExamTopicPlan(BaseModel):
    """How the exam was personalised for one topic, shown to the student before they start."""
    topic: str
    mastery: float = Field(ge=0, le=1)
    difficulty: Difficulty
    num_mcq: int
    num_short: int
    reason: str


class ExamQuestion(QuizQuestion):
    marks: float = Field(description="Marks available: 1 per MCQ, 3 per short answer")


class ExamResponse(BaseModel):
    """Answers are NOT included. Submit to get marks and feedback."""
    exam_id: str
    title: str
    user_id: str
    time_limit_minutes: int
    total_marks: float
    plan: list[ExamTopicPlan]
    questions: list[ExamQuestion]
    created_at: datetime


class ExamSubmitRequest(BaseModel):
    user_id: str = "demo"
    answers: list[QuizAnswer]
    time_taken_seconds: Optional[int] = Field(None, ge=0)


class ExamQuestionResult(BaseModel):
    question_id: str
    type: QuestionType
    question: str
    topic: str
    marks_awarded: float
    marks_available: float
    correct: bool
    your_answer: str
    correct_answer: str
    feedback: str
    missing_points: list[str] = Field([], description="Short answers: key points the student left out")


class ExamTopicScore(BaseModel):
    topic: str
    marks_awarded: float
    marks_available: float
    percentage: float


class ExamResult(BaseModel):
    exam_id: str
    user_id: str
    title: str
    marks_awarded: float
    total_marks: float
    percentage: float
    grade: Grade
    passed: bool = Field(description="percentage >= 50")
    results: list[ExamQuestionResult]
    topic_scores: list[ExamTopicScore] = Field(description="Weakest first")
    strengths: list[str]
    weak_topics: list[str]
    recommendations: list[str]
    time_taken_seconds: Optional[int] = None
    over_time: bool = False
    submitted_at: datetime


class ExamHistoryItem(BaseModel):
    exam_id: str
    title: str
    percentage: float
    grade: Grade
    marks_awarded: float
    total_marks: float
    taken_at: datetime


class ExamHistory(BaseModel):
    user_id: str
    exams: list[ExamHistoryItem]
