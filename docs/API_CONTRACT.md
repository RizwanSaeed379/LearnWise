# LearnWise API Contract (v0.2)

This document is the agreement between the **React frontend** (Sana) and the **FastAPI backend** (Rizwan).
If both sides follow it, the two halves fit together without surprises.

* **Machine-readable version:** [`openapi.json`](openapi.json) (OpenAPI 3.1). It is generated from
  `backend/app/schemas.py`, so the code and the spec never drift. Regenerate after changing a model:
  `cd backend && python scripts/export_openapi.py`
* **Interactive version:** run the backend and open <http://localhost:8000/docs> to try every endpoint.
* **Changing the contract:** agree on it together first, then update `schemas.py`, this file and `openapi.json` in the same commit.

## Conventions

| Rule | Value |
|---|---|
| Base URL | `http://localhost:8000` (frontend dev server proxies `/api` to it) |
| Format | JSON (`Content-Type: application/json`), except upload (`multipart/form-data`) |
| IDs | strings with a prefix: `doc_…`, `quiz_…`, `exam_…`, `q_…`, `card_…` |
| Times | ISO 8601 UTC, e.g. `2026-11-15T13:34:02Z` |
| Users | no login in the prototype; send `user_id` (default `"demo"`) |
| Page numbers | 1-based; for slides, the slide number |
| Citations | generated text cites passages as `[S1]`, `[S2]` = position in the `sources` array (S1 = `sources[0]`) |
| Mock mode | with `USE_MOCKS=true` every endpoint returns realistic fake data with the same shapes |

### Errors

Every error has the same shape, so the frontend needs one handler:

```json
{ "error": { "code": "unsupported_file", "message": "Only .pdf, .pptx files are supported." } }
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request` | e.g. an exam with 0 questions |
| 404 | `not_found` | unknown document/quiz/exam, or no relevant passages for the query |
| 409 | `conflict` | exam already submitted |
| 413 | `file_too_large` | upload over 25 MB |
| 415 | `unsupported_file` | not `.pdf` / `.pptx` |
| 422 | `validation_error` | request body is wrong (missing field, value out of range) |
| 501 | `not_implemented` | real pipeline part not written yet (switch on mock mode) |
| 502 | `llm_error` | LLM server unreachable or returned unusable output |

### Shared object: `SourceRef`

A passage from the student's own document that backs up the answer. This is what makes answers traceable.

```json
{
  "document_id": "doc_sample01",
  "filename": "Lecture3_NeuralNetworks.pdf",
  "page": 7,
  "chunk_id": "doc_sample01_c007",
  "snippet": "Backpropagation applies the chain rule to compute the gradient of the loss ...",
  "score": 0.86
}
```

---

## Endpoints at a glance

| Feature | Method & path |
|---|---|
| Health / LLM check | `GET /api/health` |
| Upload a document | `POST /api/documents` |
| List / get / delete documents | `GET /api/documents`, `GET /api/documents/{id}`, `DELETE /api/documents/{id}` |
| Ask your material (RAG) | `POST /api/ask` |
| Smart notes | `POST /api/notes` |
| Quiz: generate | `POST /api/quiz` |
| Quiz: submit answers | `POST /api/quiz/{quiz_id}/submit` |
| Flashcards | `POST /api/flashcards` |
| Progress | `GET /api/progress/{user_id}` |
| Adaptive practice | `POST /api/practice` |
| Mock exam: generate | `POST /api/exam` |
| Mock exam: submit for marking | `POST /api/exam/{exam_id}/submit` |
| Mock exam: result / history | `GET /api/exam/{exam_id}/result`, `GET /api/exam/history/{user_id}` |

---

## 1. Health

`GET /api/health`

```json
{
  "status": "ok",
  "mock_mode": false,
  "llm_base_url": "https://abc-123.trycloudflare.com/v1",
  "llm_model": "qwen3:8b",
  "llm_reachable": true
}
```
`llm_reachable` is `null` in mock mode. The frontend shows a small status dot from this.

## 2. Documents

### Upload: `POST /api/documents`

`multipart/form-data` with one field `file` (`.pdf` or `.pptx`, max 25 MB).

```bash
curl -F "file=@Lecture3_NeuralNetworks.pdf" http://localhost:8000/api/documents
```

**201 Created**
```json
{
  "document_id": "doc_aa5679ca",
  "filename": "Lecture3_NeuralNetworks.pdf",
  "pages": 24,
  "chunks": 61,
  "topics": ["Perceptron", "Activation functions", "Backpropagation", "Gradient descent"],
  "status": "ready",
  "uploaded_at": "2026-11-15T13:34:02Z"
}
```
`topics` feeds the topic dropdowns on the Notes, Quiz and Flashcards pages. `status` is `processing | ready | failed`
(the prototype processes synchronously, so it is always `ready` on return).

### List: `GET /api/documents`
```json
{ "documents": [ { "document_id": "doc_aa5679ca", "filename": "...", "pages": 24, "chunks": 61, "topics": ["..."], "status": "ready", "uploaded_at": "..." } ] }
```

`GET /api/documents/{document_id}` returns one `DocumentInfo`. `DELETE /api/documents/{document_id}` returns **204** with no body.

## 3. Ask your material (RAG)

`POST /api/ask`

| Field | Type | Required | Notes |
|---|---|---|---|
| `question` | string | yes | min 3 characters |
| `document_ids` | string[] \| null | no | `null` = search all documents |
| `top_k` | int | no | 1–20, default 5: how many passages to retrieve |

```json
{ "question": "What is backpropagation?", "document_ids": null, "top_k": 5 }
```

**200**
```json
{
  "answer": "Backpropagation computes how much each weight contributed to the error by applying the chain rule from the output layer backwards [S1]. The gradients are then used by gradient descent to update the weights [S2].",
  "sources": [
    { "document_id": "doc_sample01", "filename": "Lecture3_NeuralNetworks.pdf", "page": 7, "chunk_id": "doc_sample01_c007", "snippet": "Backpropagation applies the chain rule ...", "score": 0.86 },
    { "document_id": "doc_sample01", "filename": "Lecture3_NeuralNetworks.pdf", "page": 8, "chunk_id": "doc_sample01_c008", "snippet": "The computed gradients are then used by gradient descent ...", "score": 0.79 }
  ],
  "grounded": true
}
```
If nothing relevant is found, `grounded` is `false`, `sources` is `[]` and `answer` says so. The model is told never to answer from outside knowledge.

## 4. Smart notes

`POST /api/notes`

| Field | Type | Required | Notes |
|---|---|---|---|
| `topic` | string | yes | |
| `style` | `"concise"` \| `"detailed"` \| `"exam"` | no | default `concise` |
| `document_ids` | string[] \| null | no | |

```json
{ "topic": "Backpropagation", "style": "exam" }
```

**200**
```json
{
  "title": "Backpropagation",
  "style": "exam",
  "sections": [
    {
      "heading": "What is Backpropagation?",
      "content": "An algorithm that computes weight gradients using the chain rule [S1].",
      "bullets": ["Defined on page 7", "Builds on the chain rule"],
      "key_terms": ["backpropagation", "gradient"]
    },
    {
      "heading": "Likely exam questions",
      "content": "",
      "bullets": ["Derive the weight update for one neuron."],
      "key_terms": []
    }
  ],
  "sources": [ { "...": "SourceRef" } ]
}
```

## 5. Quiz

### Generate: `POST /api/quiz`

| Field | Type | Required | Notes |
|---|---|---|---|
| `topic` | string | yes | |
| `difficulty` | `"easy"` \| `"medium"` \| `"hard"` | no | default `medium` |
| `num_mcq` | int | no | 0–20, default 4 |
| `num_short` | int | no | 0–10, default 1 |
| `document_ids` | string[] \| null | no | |
| `user_id` | string | no | default `demo` |

```json
{ "topic": "Backpropagation", "difficulty": "medium", "num_mcq": 1, "num_short": 1 }
```

**200** (answers are **not** sent, so they can't be peeked at in the browser; the server keeps the answer key)
```json
{
  "quiz_id": "quiz_b495e7cc",
  "topic": "Backpropagation",
  "difficulty": "medium",
  "questions": [
    {
      "question_id": "q_e85f1c45",
      "type": "mcq",
      "question": "Which rule does backpropagation rely on?",
      "options": ["Chain rule", "Bayes' rule", "Product rule only", "L'Hopital's rule"],
      "topic": "Backpropagation",
      "difficulty": "medium",
      "source": { "...": "SourceRef" }
    },
    {
      "question_id": "q_55497e24",
      "type": "short",
      "question": "In one or two sentences, explain Backpropagation.",
      "options": null,
      "topic": "Backpropagation",
      "difficulty": "medium",
      "source": { "...": "SourceRef" }
    }
  ]
}
```
MCQs always have exactly 4 options.

### Submit: `POST /api/quiz/{quiz_id}/submit`

For an MCQ, `answer` is the **index** of the chosen option as a string (`"0"`–`"3"`). For a short answer, it is the text.

```json
{
  "user_id": "demo",
  "answers": [
    { "question_id": "q_e85f1c45", "answer": "0" },
    { "question_id": "q_55497e24", "answer": "It uses gradients" }
  ]
}
```

**200**
```json
{
  "quiz_id": "quiz_b495e7cc",
  "score": 1.17,
  "total": 2,
  "percentage": 58.5,
  "results": [
    { "question_id": "q_e85f1c45", "correct": true, "score": 1.0, "your_answer": "Chain rule", "correct_answer": "Chain rule", "explanation": "Backprop applies the chain rule layer by layer [S1].", "topic": "Backpropagation" },
    { "question_id": "q_55497e24", "correct": false, "score": 0.17, "your_answer": "It uses gradients", "correct_answer": "Backpropagation uses the chain rule to compute gradients that update the weights.", "explanation": "A good answer mentions gradients, the chain rule and weight updates.", "topic": "Backpropagation" }
  ],
  "weak_topics": ["Backpropagation"]
}
```
Short answers get partial credit (`score` 0–1, graded by the LLM). `correct` = `score >= 0.6`.
Submitting also updates the student's progress.

## 6. Flashcards

`POST /api/flashcards`

```json
{ "topic": "Backpropagation", "count": 8, "document_ids": null }
```
`count` is 1–30, default 8.

**200**
```json
{
  "topic": "Backpropagation",
  "cards": [
    { "card_id": "card_0eeabcee", "front": "Backpropagation", "back": "Algorithm that computes weight gradients using the chain rule, from output to input.", "topic": "Backpropagation", "source": { "...": "SourceRef" } }
  ]
}
```

## 7. Progress and adaptive practice

### Progress: `GET /api/progress/{user_id}`

```json
{
  "user_id": "demo",
  "topics": [
    { "topic": "Backpropagation", "attempts": 2, "correct": 1.17, "mastery": 0.542, "last_practiced": "2026-11-15T13:34:02Z" }
  ],
  "weak_topics": ["Backpropagation"],
  "recent_quizzes": [
    { "quiz_id": "quiz_b495e7cc", "topic": "Backpropagation", "difficulty": "medium", "percentage": 58.5, "taken_at": "2026-11-15T13:34:02Z" }
  ]
}
```
`mastery = (correct + 1) / (attempts + 2)` (smoothed so one wrong answer doesn't give 0%). `topics` is sorted weakest first.
A topic is **weak** when mastery < 0.6.

### Adaptive practice: `POST /api/practice`

Picks the weakest topics, re-explains each one in simpler words, and builds a fresh quiz for them. Difficulty follows
mastery: < 0.4 easy, < 0.75 medium, otherwise hard. With no history yet it starts from the uploaded documents' topics.

```json
{ "user_id": "demo", "max_topics": 2, "questions_per_topic": 3, "document_ids": null }
```

**200**
```json
{
  "user_id": "demo",
  "selected": [
    {
      "topic": "Backpropagation",
      "mastery": 0.542,
      "reason": "Your mastery is 54% after 2 questions.",
      "explanation": "Think of backpropagation like retracing your steps after getting lost ..."
    }
  ],
  "quiz": { "quiz_id": "quiz_01d6c6b8", "topic": "Adaptive practice", "difficulty": "medium", "questions": [ { "...": "QuizQuestion" } ] }
}
```
The returned quiz is submitted with the normal `POST /api/quiz/{quiz_id}/submit`.

---

## 8. Graded mock exam

A timed, marked test built from the student's own documents: the feature that goes beyond a plain
"chat with your PDF" tool. It is **personalised** (weak topics get more questions and an easier/harder level
that matches mastery) and **graded** (marks, percentage, letter grade, per-topic breakdown, feedback).

### Generate: `POST /api/exam`

```json
{
  "user_id": "demo",
  "topics": null,
  "num_mcq": 8,
  "num_short": 3,
  "difficulty": "adaptive",
  "time_limit_minutes": 30,
  "max_topics": 4,
  "document_ids": null
}
```

* `topics: null` = personalised pick: weak topics (mastery < 0.6) first, then document topics not tested yet,
  then strong topics, up to `max_topics`.
* Questions are shared across topics in proportion to `1.25 - mastery` (a 30% topic gets ~3x the questions of a 90% topic).
* `difficulty: "adaptive"` sets each topic's level from mastery (< 0.4 easy, < 0.75 medium, else hard);
  `"easy" | "medium" | "hard"` forces one level.
* Marks: MCQ = 1, short answer = 3. MCQs come first in the paper.

**201** (answers are never sent before submission)
```json
{
  "exam_id": "exam_5f2c91aa",
  "title": "Mock exam: Backpropagation, Overfitting",
  "user_id": "demo",
  "time_limit_minutes": 30,
  "total_marks": 17,
  "plan": [
    { "topic": "Backpropagation", "mastery": 0.25, "difficulty": "easy", "num_mcq": 6, "num_short": 2,
      "reason": "Weak topic: 25% mastery after 6 questions, so it gets more questions." },
    { "topic": "Overfitting", "mastery": 0.5, "difficulty": "medium", "num_mcq": 2, "num_short": 1,
      "reason": "You haven't been tested on this yet." }
  ],
  "questions": [ { "...": "QuizQuestion fields", "marks": 1 } ],
  "created_at": "2026-11-20T21:40:00Z"
}
```
**400** `bad_request` when `num_mcq + num_short == 0`.

### Submit: `POST /api/exam/{exam_id}/submit`

```json
{ "user_id": "demo", "answers": [ { "question_id": "q_1a2b3c4d", "answer": "2" } ], "time_taken_seconds": 1240 }
```
MCQ answers are the option index as a string, as in the quiz. Unanswered questions score 0.
Short answers are marked by the LLM against the reference answer with a rubric prompt
(`score` = fraction of key points covered, rounded to the nearest half mark); mock mode uses keyword overlap.

**200**
```json
{
  "exam_id": "exam_5f2c91aa",
  "user_id": "demo",
  "title": "Mock exam: Backpropagation, Overfitting",
  "marks_awarded": 11.5,
  "total_marks": 17,
  "percentage": 67.6,
  "grade": "C",
  "passed": true,
  "results": [
    {
      "question_id": "q_9f8e7d6c", "type": "short", "question": "Explain backpropagation.", "topic": "Backpropagation",
      "marks_awarded": 1.5, "marks_available": 3, "correct": false,
      "your_answer": "It uses the chain rule.", "correct_answer": "Backprop uses the chain rule to compute gradients that update the weights.",
      "feedback": "You named the chain rule but did not say what the gradients are used for.",
      "missing_points": ["gradients update the weights"]
    }
  ],
  "topic_scores": [ { "topic": "Backpropagation", "marks_awarded": 7.5, "marks_available": 12, "percentage": 62.5 } ],
  "strengths": ["Overfitting"],
  "weak_topics": [],
  "recommendations": ["Well done. Try another exam at a harder difficulty, or add more topics."],
  "time_taken_seconds": 1240,
  "over_time": false,
  "submitted_at": "2026-11-20T22:01:00Z"
}
```
Grades: A >= 85, B >= 70, C >= 55, D >= 40, else F. Pass = 50%. `topic_scores` is weakest first.
Every question also updates the student's mastery (same as a quiz), so the next exam adapts.
**404** unknown exam, **409** `conflict` if it was already submitted.

### Result: `GET /api/exam/{exam_id}/result`
Returns the same `ExamResult` again. **404** if the exam is unknown or not submitted yet.

### History: `GET /api/exam/history/{user_id}`
```json
{ "user_id": "demo", "exams": [ { "exam_id": "exam_5f2c91aa", "title": "Mock exam: ...", "percentage": 67.6, "grade": "C", "marks_awarded": 11.5, "total_marks": 17, "taken_at": "2026-11-20T22:01:00Z" } ] }
```
Newest first.
