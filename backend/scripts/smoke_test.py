"""End-to-end check of a RUNNING backend with the real models (Kaggle).

  1. start the backend:   uvicorn app.main:app        (from backend/, with your Kaggle block in .env)
  2. in another terminal: python scripts/smoke_test.py [your_lecture.pdf]

Without a file it builds the two test lectures from eval/data. It exercises every feature:
upload, ask (with citations), notes, flashcards, quiz + marking, mock exam + marking, progress,
delete, and prints one short line per step. Paste the output back if something fails.
"""
import json
import pathlib
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

API = "http://localhost:8000/api"
ROOT = pathlib.Path(__file__).resolve().parents[2]


def call(method, path, body=None, files=None, timeout=600):
    headers, data = {}, None
    if files:
        boundary = uuid.uuid4().hex
        name, content = files
        data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return (json.loads(raw) if raw else None), time.time() - t
    except urllib.error.HTTPError as e:
        raise SystemExit(f"FAIL {method} {path}: HTTP {e.code} {e.read().decode()[:500]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"FAIL: backend not reachable at {API} ({e.reason}). Is uvicorn running?")


def step(name, fn):
    try:
        msg = fn()
        print(f"OK   {name}: {msg}")
    except SystemExit as e:
        print(f"FAIL {name}: {e}")
        raise


def main():
    h, _ = call("GET", "/health")
    print(f"health: mock_mode={h['mock_mode']} llm={h['llm_model']} reachable={h['llm_reachable']} "
          f"embeddings={h.get('embedding_mode')} reachable={h.get('embeddings_reachable')}")
    if h["mock_mode"]:
        print("NOTE: backend is in MOCK mode (fake data). Paste the Kaggle block into backend/.env and restart uvicorn.")
    if not h["mock_mode"] and not h["llm_reachable"]:
        sys.exit("FAIL: the LLM is unreachable. Is the Kaggle notebook still running? Did the URL change?")

    if len(sys.argv) > 1:
        files = [pathlib.Path(sys.argv[1])]
    else:
        sys.path.insert(0, str(ROOT / "eval"))
        from run_eval import build_lectures
        files = build_lectures(pathlib.Path(tempfile.mkdtemp()))

    docs = []
    for f in files:
        d, t = call("POST", "/documents", files=(f.name, f.read_bytes()))
        docs.append(d)
        print(f"OK   upload {f.name}: {d['pages']} pages, {d['chunks']} chunks, topics {d['topics'][:5]} ({t:.1f}s)")
    ids = [d["document_id"] for d in docs]
    topic = docs[0]["topics"][min(2, len(docs[0]["topics"]) - 1)]
    question = "How does backpropagation compute gradients?" if len(sys.argv) == 1 else f"What is {topic}?"

    def ask():
        a, t = call("POST", "/ask", {"question": question, "document_ids": ids})
        pages = [f"{s['filename']} p.{s['page']}" for s in a["sources"][:3]]
        return f"grounded={a['grounded']} cites {pages} ({t:.1f}s)\n       answer: {a['answer'][:300]}"

    def notes():
        n, t = call("POST", "/notes", {"topic": topic, "style": "exam", "document_ids": ids})
        return f"'{n['title']}', {len(n['sections'])} sections: {[s['heading'] for s in n['sections']][:4]} ({t:.1f}s)"

    def cards():
        c, t = call("POST", "/flashcards", {"topic": topic, "count": 5, "document_ids": ids})
        return f"{len(c['cards'])} cards, first: {c['cards'][0]['front']!r} -> {c['cards'][0]['back'][:80]!r} ({t:.1f}s)" if c["cards"] else "0 cards!"

    def quiz():
        q, t = call("POST", "/quiz", {"topic": topic, "difficulty": "medium", "num_mcq": 3, "num_short": 1, "document_ids": ids, "user_id": "smoke"})
        ans = [{"question_id": x["question_id"], "answer": "0" if x["type"] == "mcq" else "I am not sure."} for x in q["questions"]]
        r, t2 = call("POST", f"/quiz/{q['quiz_id']}/submit", {"user_id": "smoke", "answers": ans})
        return f"{len(q['questions'])} questions ({t:.1f}s), marked {r['percentage']}% ({t2:.1f}s)\n       Q1: {q['questions'][0]['question'][:120]}"

    def exam():
        e, t = call("POST", "/exam", {"user_id": "smoke", "num_mcq": 4, "num_short": 2, "time_limit_minutes": 10, "max_topics": 2, "document_ids": ids})
        ans = [{"question_id": x["question_id"], "answer": "1" if x["type"] == "mcq" else "It uses the chain rule to compute gradients from the output layer backwards."} for x in e["questions"]]
        r, t2 = call("POST", f"/exam/{e['exam_id']}/submit", {"user_id": "smoke", "answers": ans, "time_taken_seconds": 120})
        short = next((x for x in r["results"] if x["type"] == "short"), None)
        fb = f"\n       short answer: {short['marks_awarded']}/{short['marks_available']} - {short['feedback'][:160]}" if short else ""
        return f"'{e['title']}' {len(e['questions'])} q / {e['total_marks']} marks ({t:.1f}s); grade {r['grade']} {r['percentage']}% ({t2:.1f}s){fb}"

    def progress():
        p, _ = call("GET", "/progress/smoke")
        return f"{len(p['topics'])} topics tracked, weak: {p['weak_topics'][:3]}"

    for name, fn in [("ask", ask), ("notes", notes), ("flashcards", cards), ("quiz", quiz), ("mock exam", exam), ("progress", progress)]:
        step(name, fn)
    if len(sys.argv) == 1:
        for i in ids:
            call("DELETE", f"/documents/{i}")
        print("OK   cleanup: test lectures deleted")
    print("\nAll features work end to end.")


if __name__ == "__main__":
    main()
