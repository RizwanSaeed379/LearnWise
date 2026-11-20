# User study (pilot with student testers)

The proposal's last evaluation area is **user value**: task completion, satisfaction and usefulness.
Automatic metrics are in `run_eval.py`; this is the short pilot that covers the human side.

## Setup
* 5-8 student volunteers from the course, each with one of their own lecture PDFs or slide decks.
* Backend in full mode (Kaggle Qwen3 + bge-small), the React app on one laptop.
* About 20 minutes per person. One of us observes and notes problems; we don't help unless they are stuck for over a minute.

## Tasks (tick if completed without help)
| # | Task | Done? | Time |
|---|---|---|---|
| 1 | Upload your lecture and check its topics look right | | |
| 2 | Ask two questions about it and open the cited page for one answer | | |
| 3 | Generate exam-focused notes for one topic | | |
| 4 | Take a 4-question quiz and submit it | | |
| 5 | Study 5 flashcards | | |
| 6 | Take a 10-minute graded mock exam and read the feedback | | |
| 7 | Find your weakest topic on the Progress page | | |

**Task completion rate** = completed tasks / (participants × 7).

## Questionnaire (1 = strongly disagree, 5 = strongly agree)
1. The answers were correct for my lecture.
2. The page references helped me check the answers.
3. The notes were clear and well organised.
4. The quiz and exam questions matched the difficulty I chose.
5. The marks and feedback on my short answers were fair.
6. The mock exam showed me what to revise next.
7. I would use LearnWise to prepare for my exams.
8. Overall, I am satisfied with LearnWise.

Open questions: *What was most useful? What was confusing or wrong? What would you add?*

## Rubric for generated notes (rated by us or the instructor, 1-5 each)
Clarity · Completeness · Relevance to the lecture · Organisation · Correctness

## What to report
| Measure | Value |
|---|---|
| Participants | |
| Task completion rate | |
| Mean satisfaction (Q8) | |
| Mean fairness of exam marking (Q5) | |
| Mean usefulness (Q7) | |
| Notes rubric average | |
| Top 3 problems found | |
