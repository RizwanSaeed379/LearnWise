# LearnWise AI: a Personalised Generative AI Learning and Study Assistant

**Course:** Generative AI · **Instructor:** Ms. Shahela Saif
**Group:** Rizwan Saeed (23i-3009), Sana Idrees (23i-2039)

> Draft final report. All numbers are from `eval/results/report_full.md` (full run: Qwen3-8B and bge-small on Kaggle).

---

## Abstract

LearnWise turns a student's own lecture PDFs and slide decks into grounded answers with page references, study notes,
quizzes, flashcards and a graded, personalised mock exam. It uses Retrieval-Augmented Generation (RAG): lecture text is
split into chunks and indexed two ways, as `bge-small-en-v1.5` embeddings in FAISS and as BM25 keywords. The two rankings
are fused with Reciprocal Rank Fusion, and the best passages, within a token budget, are given to an instruction-tuned
LLM (Qwen3-8B, 4-bit, on a free Kaggle T4 GPU). Prompts require citations and JSON output. Every answer is checked
against the passages it cites before it is shown, and JSON is validated. Quiz and exam results update a per-topic
mastery score that decides what the student practises next. On our test set, retrieval ranked the right page first for
**100%** of questions, **100%** of answer sentences were supported by the cited text, and the LLM marker was within
0.75 of 3 marks of the human mark on **70%** of short answers (keyword baseline: 30%).

## 1. Problem and motivation

Students study from long, differently formatted course material. Turning it into revision notes, self-tests and
explanations is slow. General chatbots can give broad or unsupported answers that ignore the course. Students also
need to move from passive reading to active practice. LearnWise keeps every output traceable to the uploaded material
and closes the loop from *study* to *practice* to *graded test* to *targeted revision*.

**Difference from NotebookLM-style tools.** "Chat with your documents" tools answer questions and summarise. LearnWise
adds an assessment loop: a timed, personalised mock exam that is marked (short answers by the LLM against a reference
answer) and graded, with per-topic results feeding back into what the student practises next.

## 2. Features

| Feature | What the student does | Generative AI contribution |
|---|---|---|
| Ask your material | Asks a question, gets an answer with clickable `[S1]` citations to pages | RAG with hybrid retrieval; answer verified against its citations; "NOT_FOUND" when the answer isn't in the material |
| Smart notes | Picks a topic and concise / detailed / exam style | Structured JSON notes (headings, bullets, key terms) from retrieved passages |
| Quiz | Picks topic, difficulty, number of MCQs / short answers | Few-shot, schema-constrained question generation; LLM marking of short answers |
| Flashcards | Flips through cards for a topic | Concept extraction into question/answer cards |
| Mock exam | Takes a timed exam built for their weak topics | Personalised paper; rubric marking with missing points; grade and revision advice |
| Progress / adaptive practice | Sees mastery per topic, practises weak topics | Topic selector picks weak topics; LLM writes a simpler explanation and a fresh quiz |

## 3. System architecture

```
 Laptop (8 GB RAM, CPU)                                  Kaggle (free T4 GPU)
 React UI ──/api──▶ FastAPI backend                      gateway (secret key)
   upload ─▶ PyMuPDF / python-pptx ─▶ chunks ──────────▶  /v1/embeddings  ─▶ bge-small-en-v1.5
              FAISS + BM25 index ◀── vectors ◀──────────
   request ─▶ FAISS + BM25 ─▶ RRF ─▶ build_context ────▶  /v1/chat/completions ─▶ Ollama: Qwen3-8B (4-bit)
              verify / validate ◀── answer / JSON ◀─────          (one Cloudflare tunnel URL)
```

* **Backend:** FastAPI (Python). One router per feature. Every request and response is a Pydantic model, so the API
  contract (`docs/API_CONTRACT.md`, `docs/openapi.json`) is generated from code. Errors share one JSON shape.
* **Frontend:** React + Vite, seven pages (Library, Ask, Notes, Quiz, Flashcards, Mock exam, Progress).
* **Models:** all models run on Kaggle (no paid API). A small gateway on Kaggle serves both the LLM (via Ollama) and the
  embedding model behind one URL protected by a secret key. The backend only knows OpenAI-compatible URLs, so the LLM
  can be swapped (local Ollama, Groq) by editing `.env`.
* **Storage:** uploaded files, the FAISS index (`vectors.npy` + `chunks.json`) and a JSON store of documents, progress,
  quizzes and exams, all under `DATA_DIR`, so restarts lose nothing. The BM25 index is rebuilt in memory from the
  stored chunk texts.
* **Mock mode:** every endpoint can return realistic fake data, so the UI was built and tested before the models ran.

## 4. Methods

### 4.1 Ingestion and chunking
PyMuPDF extracts text per PDF page. python-pptx extracts slide titles, text boxes, tables and speaker notes per slide.
Text is cleaned (soft hyphens, words split across lines, whitespace) and split into ~800-character windows with
~150-character overlap, cut at sentence or word boundaries. Chunks never cross pages, so every chunk keeps one page
number for citations. Pages with no text are skipped. A file with no text layer (scanned PDF) is rejected with a clear
message. Topics for the dropdowns come from page and slide titles, with generic titles ("Outline", "Thank you") removed.

### 4.2 Embeddings and hybrid retrieval
Chunks are embedded with `BAAI/bge-small-en-v1.5` (384 dimensions, L2-normalised, so inner product = cosine
similarity). Queries get BGE's retrieval instruction prefix. Vectors are stored in a FAISS `IndexFlatIP` (exact search).

Small embedding models can miss exact terms such as names, acronyms and symbols, so each question is also scored with
**Okapi BM25** (k1 = 1.5, b = 0.75) over the same chunks, using lower-cased, lightly stemmed words without stop words.
The dense and BM25 rankings (top 20 each) are combined with **Reciprocal Rank Fusion**:
score(d) = Σ 1 / (60 + rank of d in each list). RRF only uses ranks, so the two very different score scales never have
to be calibrated against each other. An optional **cross-encoder** (`RERANK_MODEL`, e.g. `ms-marco-MiniLM-L-6-v2`) can
re-order the fused top 20. It is off by default because it needs PyTorch on the laptop. If it fails to load, the fused
order is used.

Every passage must still reach a cosine similarity of `MIN_SCORE` (0.2), so unrelated questions return nothing
instead of weak context. Retrieval can be limited to chosen documents. If the embedding model changes, stored chunk
texts are re-embedded automatically.

### 4.3 Context building
`build_context` turns the ranked passages into the prompt's CONTEXT block:
1. passages whose text is already contained in a better-ranked passage are dropped;
2. neighbouring chunks of the same page are merged into one passage, with their 150-character overlap written once;
3. passages are added best-first until a token budget (`CONTEXT_BUDGET_TOKENS`, default 2000, ~4 characters per
   token) is reached. The best passage is always kept.

Passages are labelled `[S1] … [Sk]` with file and page. The list used for the labels is the same list the API returns,
so every citation maps to the right page.

### 4.4 Prompting and structured generation
Every prompt has a system role restricting the model to the CONTEXT passages. The passages are wrapped in
`<documents> … </documents>`, and the system prompt says text inside is material to read, never instructions to
follow. A document cannot close the block itself (**prompt-injection defence**). Rules used across tasks: cite labels,
say "NOT_FOUND" when the context lacks the answer, match the requested length and difficulty (easy = recall,
medium = apply, hard = analyse), and reply with JSON in the shape of a one-shot example (**few-shot prompting**).
Qwen3's reasoning trace is switched off (`/no_think`) for speed and clean JSON. The adapter requests JSON mode and
retries once on invalid JSON.

### 4.5 Answer verification and validation
Before an answer is shown, a verifier checks that every `[S#]` label points to a passage that was in the prompt, and
that each sentence is supported by the passages it cites (at least half its content words appear there). If fewer
than 75% of sentences pass, the model is asked once more, with feedback naming the problem. If the answer still fails,
it is shown with a "couldn't fully verify" warning (`grounded: false`) and dead labels are removed.

LLM JSON is checked before display. MCQs need exactly four distinct, non-empty options. Answers given as letters
("B") or option text are normalised to an index, and "A)" prefixes are stripped. Repeated questions, and questions
beyond the number requested, are dropped. Flashcards need both sides and unique fronts. A label that points to no
passage gives no source rather than a wrong page. Quiz questions are matched to the passage that contains their answer.

### 4.6 Personalisation
**Mastery** per topic = (correct + 1) / (attempts + 2). This is Laplace smoothing: a new topic starts at 0.5, and one
wrong answer gives 0.33, not 0. A topic is weak below 0.6. Adaptive practice picks the weakest topics, nudged towards
topics not practised recently: each day since the last attempt counts as 2% less mastery, up to 14%. Difficulty is set
from mastery (< 0.4 easy, < 0.75 medium, else hard).

### 4.7 Graded mock exam
Candidate topics are the student's choice, or weak topics first, then untested document topics, then strong topics.
Questions are shared out in proportion to (1.25 − mastery) with the largest-remainder method, so a 30%-mastery topic
gets about three times the questions of a 90% topic. MCQs are worth 1 mark and are auto-marked. Short answers are
worth 3 marks and are marked by the LLM with a rubric prompt that returns the fraction of key points covered and the
missing points, rounded to half marks. If the model's reply has no usable score, it is retried, and if that also
fails the answer is flagged for hand marking. Results give a percentage, a grade (A ≥ 85, B ≥ 70, C ≥ 55, D ≥ 40,
else F), pass at 50%, per-topic scores, strengths, weak topics and revision advice, and update mastery.

## 5. Implementation

| Part | Technology |
|---|---|
| Backend | Python 3.10+, FastAPI, Pydantic, httpx |
| Documents | PyMuPDF, python-pptx |
| Retrieval | bge-small-en-v1.5 (on Kaggle), FAISS + in-memory BM25 with RRF (laptop), optional cross-encoder |
| LLM | Qwen3-8B Q4 via Ollama on a Kaggle T4, OpenAI-compatible API |
| Hosting the models | Kaggle notebook + FastAPI gateway + Cloudflare quick tunnel |
| Frontend | React 18, Vite |
| Tests | pytest, 69 tests: mock mode, the real code path with a fake LLM, real PDF/PPTX ingestion, hybrid retrieval, context building, answer verifier, exam, evaluation smoke test |

## 6. Evaluation

Method: `eval/run_eval.py` on two lectures (5-page PDF, 4-slide PPTX; 9 chunks). The test set has 17 answerable
questions with the page that holds each answer, 3 out-of-scope questions, 10 hand-marked short answers, and quizzes on
4 topics.

| Area | Metric | Result |
|---|---|---|
| Retrieval | Hit@1 / Hit@5 / MRR | **100% / 100% / 1.0** |
| Grounding | Answer sentences supported by retrieved passages | **100%** (0 unsupported) |
| Grounding | Answers with a valid `[S#]` citation | **100%** |
| Grounding | Answers citing the page that holds the answer | **100%** |
| Grounding | Key-point coverage | **100%** |
| Grounding | Correct refusals on out-of-scope questions | **3 / 3** |
| Quiz quality | Valid-question rate after validation | **90%** (18/20) |
| Quiz quality | MCQ correct option supported by its source passage | **93.3%** |
| Exam marking | MCQ auto-marking self-check | **pass** |
| Exam marking | Short answers within 0.75/3 marks of the human mark | **70%** (keyword-overlap baseline: 30%) |
| Exam marking | Mean absolute error | **0.42 marks** (baseline 1.07) |
| Performance | Mean / p95 answer time; mean upload time | **27.2 s / 37.0 s; 23.1 s** |

**Effect of hybrid retrieval.** In the offline run (word-hash embedder in place of bge-small), adding BM25 with RRF
raised Hit@1 from 82.4% to 94.1% and MRR from 0.873 to 0.941, and answers citing the right page from 82.4% to 94.1%.
Turning it off (`HYBRID_RETRIEVAL=false`) gives the old numbers back exactly. With bge-small, retrieval was already
perfect on this test set, so the full run cannot show a difference.

**Discussion.** Grounding is at 100% on every measure. Earlier runs were at 56.6% supported sentences, because the
model padded answers with outside facts. Stricter prompts and the answer verifier fixed this. The LLM marker clearly
beats the keyword baseline (MAE 0.42 vs 1.07 marks), but it varies between runs: the previous full run gave 0.32. The
marking code did not change between those runs, so the difference most likely comes from the model's output varying
from run to run. Response times are dominated by the Kaggle round trip through the tunnel. Each retrieval took about
22 s, mostly the remote query embedding, and quiz and exam generation take 1-2 minutes.

## 7. Limitations

* **The test set is small** (two lectures, 9 chunks). Perfect retrieval here does not show how the system does on a
  full course; results may differ on longer documents and other subjects.
* The "supported sentence" check, both in the evaluation and in the runtime verifier, is a word-overlap proxy, not a
  test of meaning. A sentence can reuse the passage's words and still be wrong, and a correct paraphrase can fail.
* Scanned PDFs need OCR, which is not supported.
* Kaggle sessions last up to 12 hours and the tunnel URL changes on restart. Every request pays the tunnel latency.
* No user accounts: the prototype uses one `user_id`.
* **No user study yet.** The proposal's user-value measures (task completion, satisfaction, usefulness) were not
  collected. The pilot plan is in `eval/user_study.md`.

## 8. Future work

Run the pilot user study with 5-8 students; evaluate on full-length lectures with a larger question set; mark each
short answer several times and take the median, to make the marker steadier; turn on the cross-encoder re-ranker and
measure it; OCR for scanned documents; user accounts and saved study spaces; question difficulty calibration from
student results; a teacher mode for drafting quizzes from approved material.

## 9. Conclusion

LearnWise demonstrates the full GenAI workflow from the proposal: Transformer LLM generation, prompt engineering,
few-shot and structured generation, embeddings and hybrid semantic + keyword search, RAG with page citations,
runtime answer verification, validation, and feedback-driven personalisation. It extends this with a graded,
personalised mock exam.

## References

1. Government of Pakistan, *Pakistan Economic Survey 2024-25*, Education chapter (higher-education enrolment).
2. UNESCO (2023), *Guidance for Generative AI in Education and Research*.
3. Lewis et al. (2020), "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", NeurIPS.
4. Xiao et al. (2023), "C-Pack: Packaged Resources to Advance General Chinese Embedding" (BGE embedding models).
5. Johnson, Douze, Jégou (2019), "Billion-scale similarity search with GPUs" (FAISS), IEEE Transactions on Big Data.
6. Qwen Team (2025), *Qwen3 Technical Report*.
7. Robertson, Zaragoza (2009), "The Probabilistic Relevance Framework: BM25 and Beyond", Foundations and Trends in IR.
8. Cormack, Clarke, Büttcher (2009), "Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods", SIGIR.
