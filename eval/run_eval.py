"""LearnWise evaluation (proposal section 9).

Measures, on a fixed test set:
  1. Ingestion      upload time, pages, chunks, detected topics
  2. Retrieval      hit@1, hit@k and MRR: is the page that holds the answer retrieved?
  3. Grounding      answers that cite a passage, cite the right page, cover the key points,
                    % of answer sentences supported by the retrieved text, and correct
                    refusals for questions that are NOT in the material
  4. Quiz quality   valid-question rate after validation, 4 distinct options, answer key
                    consistent, source attached, correct option supported by its passage
  5. Exam marking   MCQ auto-marking self-check, and short-answer marking vs. human marks
  6. Performance    response time per endpoint (mean, p95)

Usage (from the learnwise/ folder):
  python eval/run_eval.py                 # real system: settings from backend/.env (LLM on Kaggle, bge-small)
  python eval/run_eval.py --offline       # no LLM / no model download: stand-ins, checks the plumbing only
  python eval/run_eval.py --retrieval-only
  python eval/run_eval.py --docs my1.pdf my2.pptx --questions my_questions.json

Results: eval/results/results_<mode>.json and eval/results/report_<mode>.md
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
BACKEND = ROOT / "backend"
STOP = set("the a an of to in and or is are was were be by for with on at as it its this that from which what why how when who does do can into than then each".split())


# ---------------------------------------------------------------- test documents
def build_lectures(out_dir: Path) -> list[Path]:
    """Turn eval/data/lectures.json into a real PDF and a real PPTX."""
    import pymupdf
    from pptx import Presentation

    spec = json.loads((EVAL / "data" / "lectures.json").read_text(encoding="utf-8"))
    paths = []
    for lec in spec["lectures"]:
        p = out_dir / lec["filename"]
        if "pages" in lec:
            doc = pymupdf.open()
            for text in lec["pages"]:
                doc.new_page().insert_textbox(pymupdf.Rect(60, 60, 540, 800), text, fontsize=11)
            doc.save(str(p))
        else:
            prs = Presentation()
            for title, body in lec["slides"]:
                s = prs.slides.add_slide(prs.slide_layouts[1])
                s.shapes.title.text = title
                s.placeholders[1].text = body
            prs.save(str(p))
        paths.append(p)
    return paths


# ---------------------------------------------------------------- offline stand-ins
class HashEmbedder:
    """Bag of hashed words. Only for --offline: real runs use bge-small."""

    def encode(self, texts, query=False):
        import numpy as np

        out = np.zeros((len(texts), 512), dtype="float32")
        for i, t in enumerate(texts):
            for w in _words(t):
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % 512] += 1
        out /= np.linalg.norm(out, axis=1, keepdims=True) + 1e-9
        return out


class ExtractiveLLM:
    """Only for --offline: answers by quoting the best passage, so the pipeline can be checked without a GPU."""

    async def chat(self, messages, **kw):
        p = messages[-1]["content"]
        m = re.search(r"\[S1\] \([^)]*\)\n(.+?)(?:\n\n\[S2\]|\n\nQUESTION:|$)", p, re.S)
        if "QUESTION:" in p and not m:
            return "NOT_FOUND"
        return (_sentences(m.group(1).split("\n", 1)[-1])[0] + " [S1]") if m else "Explanation."

    async def chat_json(self, messages, **kw):
        p = messages[-1]["content"]
        if "Grade the student" in p:
            from app.services import mock

            ref = re.search(r"REFERENCE ANSWER: (.*)\n", p).group(1)
            stu = re.search(r"STUDENT ANSWER: (.*)\n", p).group(1)
            return {"score": mock.grade_short(ref, "" if stu == "(blank)" else stu), "feedback": "keyword overlap", "missing_points": []}
        if "multiple-choice" in p:
            passages = re.findall(r"\[S(\d+)\] \([^)]*\)\n(.+?)(?=\n\n\[S|\n\nTOPIC:)", p, re.S)
            sents = [(f"S{n}", s) for n, t in passages for s in _sentences(t.split("\n", 1)[-1])]
            fillers = ["The lecture does not cover this.", "It only applies to linear models.", "It removes the need for training data."]
            qs = []
            for i in range(min(len(sents), 4)):
                label, right = sents[i]
                opts = ([right] + [s for _, s in sents[i + 1 : i + 4]] + fillers)[:4]
                qs.append({"type": "mcq", "question": "Which statement matches the lecture?", "options": opts, "answer": "0", "explanation": right, "source": label})
            if sents:
                qs.append({"type": "short", "question": "Summarise the main idea.", "answer": sents[0][1], "explanation": sents[0][1], "source": sents[0][0]})
            return {"questions": qs}
        return {}


# ---------------------------------------------------------------- helpers
def _stem(w: str) -> str:
    """Very light stemming so 'layers'/'layer' and 'detects'/'detect' count as the same word."""
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def _words(t: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in STOP]


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", t.replace("\n", " ")) if len(s.strip()) > 3]


def supported(sentence: str, passages: list[str], need: float = 0.5) -> bool:
    """A sentence counts as supported when at least half its content words appear in the retrieved passages."""
    words = set(_words(re.sub(r"\[S\d+\]", "", sentence)))
    if not words:
        return True
    pool = set(_words(" ".join(passages)))
    return len(words & pool) / len(words) >= need


def stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    xs = sorted(xs)
    return {"n": len(xs), "mean_s": round(statistics.mean(xs), 3), "p95_s": round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 3), "max_s": round(xs[-1], 3)}


def pct(a, b):
    return round(100 * a / b, 1) if b else None


class Timer:
    def __init__(self):
        self.t = {}

    def run(self, name, fn, *a, **kw):
        t0 = time.perf_counter()
        r = fn(*a, **kw)
        self.t.setdefault(name, []).append(time.perf_counter() - t0)
        return r


# ---------------------------------------------------------------- the evaluation
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="stand-in embedder and LLM (no GPU, no downloads)")
    ap.add_argument("--retrieval-only", action="store_true", help="skip everything that needs the LLM")
    ap.add_argument("--docs", nargs="*", help="your own lecture files (default: build the test lectures)")
    ap.add_argument("--questions", default=str(EVAL / "data" / "questions.json"))
    ap.add_argument("--grading", default=str(EVAL / "data" / "grading_cases.json"))
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--quiz-topics", type=int, default=4)
    ap.add_argument("--out", default=str(EVAL / "results"))
    args = ap.parse_args()
    mode = "offline" if args.offline else "retrieval" if args.retrieval_only else "full"

    work = Path(tempfile.mkdtemp(prefix="learnwise-eval-"))
    os.chdir(BACKEND)  # so backend/.env is read
    os.environ.update(USE_MOCKS="false", MOCK_RETRIEVAL="false", DATA_DIR=str(work / "data"))
    sys.path.insert(0, str(BACKEND))

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app
    from app.prompts import templates
    from app.routers.exam import _mark_short
    from app.schemas import ExamQuestion
    from app.services import exam as exam_svc
    from app.services import pipeline, store
    from app.services.llm import get_llm

    s = get_settings()
    if args.offline:
        pipeline.set_embedder(HashEmbedder())
        app.dependency_overrides[get_llm] = lambda: ExtractiveLLM()
        s.min_score = 0.15
    llm = ExtractiveLLM() if args.offline else get_llm()
    c = TestClient(app)
    T = Timer()
    R: dict = {"mode": mode, "settings": {"llm_model": "extractive stand-in (offline)" if args.offline else s.llm_model, "llm_base_url": None if args.offline else s.llm_base_url,
               "embedding_model": "hash (offline stand-in)" if args.offline else s.embedding_model, "chunk_size": s.chunk_size,
               "chunk_overlap": s.chunk_overlap, "top_k": args.top_k, "min_score": s.min_score}}
    print(f"LearnWise evaluation, mode={mode}")

    # 1. ingestion
    docs = [Path(d) for d in args.docs] if args.docs else build_lectures(work)
    R["ingestion"], doc_ids = [], {}
    for p in docs:
        r = T.run("upload", c.post, "/api/documents", files={"file": (p.name, p.read_bytes())})
        if r.status_code != 201:
            sys.exit(f"Upload of {p.name} failed: {r.json()}")
        d = r.json()
        doc_ids[p.name] = d["document_id"]
        R["ingestion"].append({"file": p.name, "pages": d["pages"], "chunks": d["chunks"], "topics": d["topics"], "seconds": round(T.t["upload"][-1], 2)})
        print(f"  ingested {p.name}: {d['pages']} pages, {d['chunks']} chunks, topics={d['topics']}")

    qs = json.loads(Path(args.questions).read_text(encoding="utf-8"))["questions"]
    answerable = [q for q in qs if q.get("answerable", True)]
    unanswerable = [q for q in qs if not q.get("answerable", True)]

    # 2. retrieval
    hits1 = hitsk = 0
    rr = []
    per_q = []
    for q in answerable:
        src = T.run("retrieve", pipeline.retrieve, q["q"], None, args.top_k)
        rank = next((i + 1 for i, x in enumerate(src) if x.filename == q["file"] and x.page == q["page"]), None)
        hits1 += rank == 1
        hitsk += rank is not None
        rr.append(1 / rank if rank else 0.0)
        per_q.append({"q": q["q"], "expected": f"{q['file']} p.{q['page']}", "rank": rank, "top": [f"{x.filename} p.{x.page} ({x.score})" for x in src[:3]]})
    R["retrieval"] = {"questions": len(answerable), "hit@1_pct": pct(hits1, len(answerable)), f"hit@{args.top_k}_pct": pct(hitsk, len(answerable)),
                      "mrr": round(statistics.mean(rr), 3) if rr else None, "per_question": per_q}
    print(f"  retrieval: hit@1 {R['retrieval']['hit@1_pct']}%, hit@{args.top_k} {R['retrieval'][f'hit@{args.top_k}_pct']}%, MRR {R['retrieval']['mrr']}")

    if not args.retrieval_only:
        # 3. grounding
        rows, refusals = [], 0
        for q in answerable:
            r = T.run("ask", c.post, "/api/ask", json={"question": q["q"], "top_k": args.top_k})
            body = r.json() if r.status_code == 200 else {"answer": "", "sources": [], "grounded": False}
            ans, src = body["answer"], body["sources"]
            labels = [int(n) for n in re.findall(r"\[S(\d+)\]", ans)]
            valid = bool(labels) and all(1 <= n <= len(src) for n in labels)
            cited = [src[n - 1] for n in labels if 1 <= n <= len(src)]
            sents = [x for x in _sentences(ans)]
            sup = [supported(x, [y["snippet"] for y in src]) for x in sents]
            kp = q.get("key_points", [])
            rows.append({
                "q": q["q"], "grounded": body["grounded"], "valid_citation": valid,
                "cites_expected_page": any(x["filename"] == q["file"] and x["page"] == q["page"] for x in cited),
                "key_points_covered": round(sum(k.lower() in ans.lower() for k in kp) / len(kp), 2) if kp else None,
                "sentences": len(sents), "supported_sentences": sum(sup), "answer": ans,
            })
        for q in unanswerable:
            r = T.run("ask", c.post, "/api/ask", json={"question": q["q"], "top_k": args.top_k})
            ok = r.status_code == 404 or (r.status_code == 200 and not r.json()["grounded"])
            refusals += ok
            rows.append({"q": q["q"], "answerable": False, "correct_refusal": ok, "answer": r.json().get("answer", r.json().get("error", {}).get("message"))})
        a = [x for x in rows if "valid_citation" in x]
        n_sent = sum(x["sentences"] for x in a)
        kps = [x["key_points_covered"] for x in a if x["key_points_covered"] is not None]
        R["grounding"] = {
            "answered_pct": pct(sum(x["grounded"] for x in a), len(a)),
            "valid_citation_pct": pct(sum(x["valid_citation"] for x in a), len(a)),
            "cites_expected_page_pct": pct(sum(x["cites_expected_page"] for x in a), len(a)),
            "supported_sentences_pct": pct(sum(x["supported_sentences"] for x in a), n_sent),
            "unsupported_sentences": n_sent - sum(x["supported_sentences"] for x in a),
            "key_point_coverage_pct": round(100 * statistics.mean(kps), 1) if kps else None,
            "correct_refusal_pct": pct(refusals, len(unanswerable)),
            "per_question": rows,
        }
        g = R["grounding"]
        print(f"  grounding: {g['supported_sentences_pct']}% sentences supported, {g['valid_citation_pct']}% cite, {g['cites_expected_page_pct']}% cite right page, refusals {g['correct_refusal_pct']}%")

        # 4. quiz quality
        topics = [t for d in R["ingestion"] for t in d["topics"]][: args.quiz_topics]
        req_mcq, req_short, qrows = 4, 1, []
        for t in topics:
            r = T.run("quiz", c.post, "/api/quiz", json={"topic": t, "difficulty": "medium", "num_mcq": req_mcq, "num_short": req_short, "user_id": "eval"})
            if r.status_code != 200:
                qrows.append({"topic": t, "requested": req_mcq + req_short, "valid": 0, "error": r.json()["error"]["message"]})
                continue
            quiz = r.json()
            key = store.quizzes[quiz["quiz_id"]]["answers"]
            for qq in quiz["questions"]:
                ans, expl = key[qq["question_id"]]
                row = {"topic": t, "type": qq["type"], "question": qq["question"], "has_source": qq["source"] is not None, "has_explanation": bool(expl)}
                if qq["type"] == "mcq":
                    opts = qq["options"]
                    row["distinct_options"] = len({o.strip().lower() for o in opts}) == 4
                    row["key_valid"] = ans in {"0", "1", "2", "3"}
                    row["answer_supported"] = bool(qq["source"]) and supported(opts[int(ans)], [qq["source"]["snippet"]])
                qrows.append(row)
            qrows.append({"topic": t, "requested": req_mcq + req_short, "valid": len(quiz["questions"])})
        reqs = [x for x in qrows if "requested" in x]
        items = [x for x in qrows if "type" in x]
        mcqs = [x for x in items if x["type"] == "mcq"]
        R["quiz"] = {
            "topics": topics, "requested": sum(x["requested"] for x in reqs), "valid_after_validation": sum(x["valid"] for x in reqs),
            "valid_question_rate_pct": pct(sum(x["valid"] for x in reqs), sum(x["requested"] for x in reqs)),
            "mcq_distinct_options_pct": pct(sum(x["distinct_options"] for x in mcqs), len(mcqs)),
            "mcq_answer_key_valid_pct": pct(sum(x["key_valid"] for x in mcqs), len(mcqs)),
            "mcq_answer_supported_by_source_pct": pct(sum(x["answer_supported"] for x in mcqs), len(mcqs)),
            "has_source_pct": pct(sum(x["has_source"] for x in items), len(items)),
            "has_explanation_pct": pct(sum(x["has_explanation"] for x in items), len(items)),
            "items": qrows,
        }
        print(f"  quiz: {R['quiz']['valid_question_rate_pct']}% valid, {R['quiz']['mcq_answer_supported_by_source_pct']}% MCQ answers supported by source")

        # 5. exam marking
        e = T.run("exam_create", c.post, "/api/exam", json={"user_id": "eval_exam", "topics": topics[:2] or None, "num_mcq": 4, "num_short": 1}).json()
        if "exam_id" in e:
            keys = store.exams[e["exam_id"]]["answers"]
            # answer every MCQ with its key: all must get full marks
            right = [{"question_id": q["question_id"], "answer": keys[q["question_id"]][0]} for q in e["questions"] if q["type"] == "mcq"]
            res = T.run("exam_submit", c.post, f"/api/exam/{e['exam_id']}/submit", json={"user_id": "eval_exam", "answers": right}).json()
            mcq = [x for x in res.get("results", []) if x["type"] == "mcq"]
            mcq_ok = bool(mcq) and all(x["marks_awarded"] == x["marks_available"] for x in mcq)
        else:
            mcq_ok = False
        cases = json.loads(Path(args.grading).read_text(encoding="utf-8"))["cases"]
        tol, grows = 0.25, []

        async def mark_all():
            out = []
            for k in cases:
                q = ExamQuestion(question_id="g", type="short", question=k["question"], options=None, topic="eval", difficulty="medium", marks=exam_svc.SHORT_MARKS)
                t0 = time.perf_counter()
                frac, fb, missing = await _mark_short(q, k["reference"], "", k["student"], llm)
                T.t.setdefault("grade_short", []).append(time.perf_counter() - t0)
                awarded = exam_svc.round_half(frac * q.marks) / q.marks
                out.append({"student": k["student"], "expected": k["expected"], "given": round(awarded, 2), "ok": abs(awarded - k["expected"]) <= tol, "feedback": fb, "missing_points": missing})
            return out

        grows = asyncio.run(mark_all())
        R["exam_marking"] = {
            "mcq_self_check_100pct": mcq_ok,
            "short_answer_cases": len(grows),
            "within_tolerance_pct": pct(sum(x["ok"] for x in grows), len(grows)),
            "mean_abs_error_marks": round(statistics.mean(abs(x["given"] - x["expected"]) * exam_svc.SHORT_MARKS for x in grows), 2) if grows else None,
            "tolerance": f"±{tol} of the marks ({tol * exam_svc.SHORT_MARKS:g} of {exam_svc.SHORT_MARKS:g})",
            "cases": grows,
        }
        print(f"  exam marking: MCQ self-check {'ok' if mcq_ok else 'FAILED'}, short answers {R['exam_marking']['within_tolerance_pct']}% within tolerance, MAE {R['exam_marking']['mean_abs_error_marks']} marks")

    R["performance"] = {k: stats(v) for k, v in T.t.items()}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"results_{mode}.json").write_text(json.dumps(R, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / f"report_{mode}.md").write_text(report(R, args.top_k), encoding="utf-8")
    print(f"wrote {out / f'results_{mode}.json'} and {out / f'report_{mode}.md'}")
    return R


def report(R: dict, k: int) -> str:
    st = R["settings"]
    L = [f"# LearnWise evaluation results ({R['mode']} mode)", ""]
    if R["mode"] == "offline":
        L += ["> **Offline mode:** a word-hash embedder and an extractive stand-in LLM replace bge-small and Qwen3.",
              "> These numbers only show the pipeline works end to end. Run `python eval/run_eval.py` with the Kaggle",
              "> server up for the numbers that go in the report.", ""]
    L += [f"LLM: `{st['llm_model']}` · embeddings: `{st['embedding_model']}` · chunk {st['chunk_size']}/{st['chunk_overlap']} · top-k {st['top_k']} · min score {st['min_score']}", "",
          "## Ingestion", "", "| File | Pages | Chunks | Time (s) | Topics |", "|---|---|---|---|---|"]
    L += [f"| {d['file']} | {d['pages']} | {d['chunks']} | {d['seconds']} | {', '.join(d['topics'])} |" for d in R["ingestion"]]
    r = R["retrieval"]
    L += ["", "## Retrieval", "", "| Metric | Value |", "|---|---|", f"| Questions | {r['questions']} |", f"| Hit@1 | {r['hit@1_pct']}% |", f"| Hit@{k} | {r[f'hit@{k}_pct']}% |", f"| MRR | {r['mrr']} |"]
    if "grounding" in R:
        g = R["grounding"]
        L += ["", "## Grounding and factuality", "", "| Metric | Value |", "|---|---|",
              f"| Answerable questions answered | {g['answered_pct']}% |",
              f"| Answers with a valid [S#] citation | {g['valid_citation_pct']}% |",
              f"| Answers citing the page that holds the answer | {g['cites_expected_page_pct']}% |",
              f"| Answer sentences supported by retrieved passages | {g['supported_sentences_pct']}% ({g['unsupported_sentences']} unsupported) |",
              f"| Key-point coverage | {g['key_point_coverage_pct']}% |",
              f"| Correct refusals on out-of-scope questions | {g['correct_refusal_pct']}% |"]
        q = R["quiz"]
        L += ["", "## Quiz quality", "", "| Metric | Value |", "|---|---|",
              f"| Valid-question rate (after validation) | {q['valid_question_rate_pct']}% ({q['valid_after_validation']}/{q['requested']}) |",
              f"| MCQs with 4 distinct options | {q['mcq_distinct_options_pct']}% |",
              f"| MCQ answer key valid | {q['mcq_answer_key_valid_pct']}% |",
              f"| MCQ correct option supported by its source passage | {q['mcq_answer_supported_by_source_pct']}% |",
              f"| Questions with a source page | {q['has_source_pct']}% |",
              f"| Questions with an explanation | {q['has_explanation_pct']}% |"]
        e = R["exam_marking"]
        L += ["", "## Mock exam marking", "", "| Metric | Value |", "|---|---|",
              f"| MCQ auto-marking self-check (every MCQ answered with its key gets full marks) | {'pass' if e['mcq_self_check_100pct'] else 'FAIL'} |",
              f"| Short answers marked within {e['tolerance']} of the human mark | {e['within_tolerance_pct']}% ({e['short_answer_cases']} cases) |",
              f"| Mean absolute error | {e['mean_abs_error_marks']} marks |"]
    L += ["", "## Response time", "", "| Step | n | Mean (s) | p95 (s) | Max (s) |", "|---|---|---|---|---|"]
    L += [f"| {name} | {v['n']} | {v.get('mean_s')} | {v.get('p95_s')} | {v.get('max_s')} |" for name, v in R["performance"].items()]
    L += ["", "## How the metrics are computed", "",
          "* **Hit@k / MRR:** a question is a hit when the page (or slide) listed in `eval/data/questions.json` is among the top-k retrieved chunks; MRR averages 1/rank.",
          "* **Supported sentence:** at least half of the sentence's content words (lightly stemmed, so plurals and -ed/-ing forms match) appear in the passages retrieved for it. A cheap, automatic proxy for the proposal's \"% of claims supported\"; spot-check a sample by hand for the report.",
          "* **Correct refusal:** for questions not in the material, the API returns 404 (nothing relevant retrieved) or `grounded: false`.",
          "* **Answer supported by source:** the correct MCQ option's content words appear in the passage the question cites.",
          "* **Exam marking:** the system's short-answer mark is compared with the human mark in `eval/data/grading_cases.json`.",
          "* User satisfaction is measured separately with the pilot survey in `eval/user_study.md`."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
