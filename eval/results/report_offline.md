# LearnWise evaluation results (offline mode)

> **Offline mode:** a word-hash embedder and an extractive stand-in LLM replace bge-small and Qwen3.
> These numbers only show the pipeline works end to end. Run `python eval/run_eval.py` with the Kaggle
> server up for the numbers that go in the report.

LLM: `extractive stand-in (offline)` · embeddings: `hash (offline stand-in)` · chunk 800/150 · top-k 5 · min score 0.15

## Ingestion

| File | Pages | Chunks | Time (s) | Topics |
|---|---|---|---|---|
| Lecture3_NeuralNetworks.pdf | 5 | 5 | 0.06 | Perceptron, Activation Functions, Backpropagation, Gradient Descent, Overfitting and Regularisation |
| Lecture4_CNNs.pptx | 4 | 4 | 0.01 | Convolutional Layers, Stride and Padding, Pooling, Transfer Learning |

## Retrieval

| Metric | Value |
|---|---|
| Questions | 17 |
| Hit@1 | 88.2% |
| Hit@5 | 88.2% |
| MRR | 0.882 |

## Grounding and factuality

| Metric | Value |
|---|---|
| Answerable questions answered | 88.2% |
| Answers with a valid [S#] citation | 88.2% |
| Answers citing the page that holds the answer | 88.2% |
| Answer sentences supported by retrieved passages | 100.0% (0 unsupported) |
| Key-point coverage | 47.1% |
| Correct refusals on out-of-scope questions | 100.0% |

## Quiz quality

| Metric | Value |
|---|---|
| Valid-question rate (after validation) | 40.0% (8/20) |
| MCQs with 4 distinct options | 100.0% |
| MCQ answer key valid | 100.0% |
| MCQ correct option supported by its source passage | 100.0% |
| Questions with a source page | 100.0% |
| Questions with an explanation | 100.0% |

## Mock exam marking

| Metric | Value |
|---|---|
| MCQ auto-marking self-check (every MCQ answered with its key gets full marks) | pass |
| Short answers marked within ±0.25 of the marks (0.75 of 3) of the human mark | 30.0% (10 cases) |
| Mean absolute error | 1.07 marks |

## Response time

| Step | n | Mean (s) | p95 (s) | Max (s) |
|---|---|---|---|---|
| upload | 2 | 0.037 | 0.063 | 0.063 |
| retrieve | 17 | 0.0 | 0.0 | 0.0 |
| ask | 20 | 0.004 | 0.007 | 0.007 |
| quiz | 4 | 0.006 | 0.008 | 0.008 |
| exam_create | 1 | 0.008 | 0.008 | 0.008 |
| exam_submit | 1 | 0.006 | 0.006 | 0.006 |
| grade_short | 10 | 0.0 | 0.0 | 0.0 |

## How the metrics are computed

* **Hit@k / MRR:** a question is a hit when the page (or slide) listed in `eval/data/questions.json` is among the top-k retrieved chunks; MRR averages 1/rank.
* **Supported sentence:** at least half of the sentence's content words appear in the passages retrieved for it. A cheap, automatic proxy for the proposal's "% of claims supported"; spot-check a sample by hand for the report.
* **Correct refusal:** for questions not in the material, the API returns 404 (nothing relevant retrieved) or `grounded: false`.
* **Answer supported by source:** the correct MCQ option's content words appear in the passage the question cites.
* **Exam marking:** the system's short-answer mark is compared with the human mark in `eval/data/grading_cases.json`.
* User satisfaction is measured separately with the pilot survey in `eval/user_study.md`.
