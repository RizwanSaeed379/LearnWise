# Evaluation

Covers the evaluation plan in section 9 of the proposal.

| Proposal area | How we measure it | Where |
|---|---|---|
| Grounding and factuality | % of answer sentences supported by the retrieved passages, valid `[S#]` citations, citing the right page, refusing out-of-scope questions | `run_eval.py` |
| Retrieval (supports grounding) | Hit@1, Hit@5 and MRR of the page that holds the answer | `run_eval.py` |
| Quiz quality | valid-question rate after validation, 4 distinct options, answer key consistent, correct option supported by its source | `run_eval.py` |
| Mock exam marking | MCQ auto-marking self-check; short-answer marks vs. human marks (10 cases) | `run_eval.py` |
| System performance | upload, retrieval and generation time (mean, p95) | `run_eval.py` |
| Generation quality, user value | notes rubric, task completion, satisfaction survey | [`user_study.md`](user_study.md) |

## Test set (`data/`)

* `lectures.json`: two short lectures (a 5-page PDF on neural networks and a 4-slide PPTX on CNNs). The script builds
  real `.pdf` / `.pptx` files from it, so the full ingestion path runs.
* `questions.json`: 17 questions with the page/slide that holds the answer and the key points a correct answer needs,
  plus 3 questions that are **not** in the material (the system should refuse them).
* `grading_cases.json`: 10 student answers to short questions with the mark a fair human marker would give
  (full, half, zero credit).

To evaluate on your own lectures, write a `questions.json` in the same format and run
`python eval/run_eval.py --docs lec1.pdf lec2.pptx --questions my_questions.json`.

## Running it

From the `learnwise/` folder, with the backend packages installed (`pip install -r backend/requirements-ml.txt`):

```bash
# 1. the real system: run the Kaggle notebook, paste its block into backend/.env, then
python eval/run_eval.py
# 2. retrieval only (no LLM calls, still uses bge-small)
python eval/run_eval.py --retrieval-only
# 3. offline smoke test (no GPU, no model download; checks the plumbing, not quality)
python eval/run_eval.py --offline
```

Each run writes `results/results_<mode>.json` (every question, answer and score) and `results/report_<mode>.md`
(tables ready to paste into the report). The backend's normal data folder is not touched: the run uses a temporary one.

## Results so far

Only the **offline** run exists so far (`results/report_offline.md`): it was made without the GPU model, using a
word-hash embedder and an extractive stand-in LLM. It shows the pipeline works end to end. It is **not** a quality
result and should not go in the report as one. Three things it already shows:

* Ingestion, retrieval, citations, refusals and MCQ marking work end to end on a real PDF and PPTX.
* Even a crude word-matching retriever finds the right page for 15 of 17 questions; the two misses
  ("Why is ReLU preferred over sigmoid?", "Name two regularisation techniques") are paraphrases, which is exactly
  what a semantic embedder like bge-small is for. Compare with the full run.
* Keyword-overlap marking of short answers agrees with the human mark in only 30% of cases (mean error 1.07 of 3
  marks). That is the baseline for the LLM rubric marker in the mock exam: the full run should beat it clearly.

## Write-up template for the report

> We evaluated LearnWise on two lectures (a 5-page PDF and a 4-slide deck) with 17 answerable and 3 out-of-scope
> questions, 10 hand-marked short answers, and quizzes for 4 topics, using Qwen3-8B (4-bit, Kaggle T4) and
> bge-small-en-v1.5 embeddings.
>
> **Retrieval** found the page containing the answer in the top 5 for __% of questions (Hit@1 __%, MRR __).
> **Grounding:** __% of answer sentences were supported by the retrieved passages (__ unsupported sentences in
> total), __% of answers cited the correct page, and the system refused __ of 3 out-of-scope questions.
> **Quiz quality:** __% of requested questions passed validation; __% of MCQs had their correct option supported
> by the cited passage. **Mock exam marking:** MCQ auto-marking was exact; the LLM marker's short-answer marks were
> within 0.75 of 3 marks of the human mark in __% of cases (mean error __ marks), against 30% for a keyword-overlap
> baseline. **Performance:** answering took __ s on average (p95 __ s); uploading a lecture took __ s.
> **Users:** __ students completed __% of tasks and rated overall satisfaction __/5 (see user_study.md).
>
> Limitations: the "supported sentence" check is a word-overlap proxy, so we also checked __ answers by hand;
> scanned PDFs are not supported (no OCR); the test set is small.

Fill the blanks from `results/report_full.md`.
