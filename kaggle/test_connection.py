"""Check that your laptop can reach the models running on Kaggle (or Ollama / Groq).

No packages needed, plain Python 3. After pasting the notebook's lines into backend/.env:

    python kaggle/test_connection.py                     # reads backend/.env
    python kaggle/test_connection.py https://xxxx.trycloudflare.com/v1 YOUR_KEY

It checks: the server answers (and the key works), the LLM replies, it returns clean JSON
(which notes/quiz/flashcards depend on), and the embedding model works (which search depends on).
"""
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request


def read_env() -> dict:
    env = {}
    path = pathlib.Path(__file__).resolve().parents[1] / "backend" / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def call(url: str, body: dict | None = None, key: str = "not-needed", timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "ngrok-skip-browser-warning": "true", "User-Agent": "learnwise-test"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> None:
    env = read_env()
    base = (sys.argv[1] if len(sys.argv) > 1 else env.get("LLM_BASE_URL", "")).rstrip("/")
    key = sys.argv[2] if len(sys.argv) > 2 else env.get("LLM_API_KEY", "not-needed")
    model = env.get("LLM_MODEL", "qwen3:8b")
    emb_base = (sys.argv[1] if len(sys.argv) > 1 else env.get("EMBEDDING_BASE_URL", "")).rstrip("/")
    emb_key = key if len(sys.argv) > 2 else env.get("EMBEDDING_API_KEY", key)
    emb_model = env.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    if not base:
        sys.exit("Give the URL: python kaggle/test_connection.py https://xxxx.trycloudflare.com/v1")
    if not base.endswith("/v1"):
        print("note: URL usually ends with /v1, e.g. https://xxxx.trycloudflare.com/v1")

    print(f"1) GET {base}/models")
    try:
        models = [m["id"] for m in call(f"{base}/models", key=key, timeout=15)["data"]]
    except urllib.error.HTTPError as e:
        hint = "The key is wrong: copy LLM_API_KEY again from the notebook's last block." if e.code == 401 else "Is the notebook still running?"
        sys.exit(f"   FAIL: HTTP {e.code}. {hint}")
    except Exception as e:
        sys.exit(f"   FAIL: {e}\n   Is the Kaggle notebook still running? Did the URL change after a restart?")
    print(f"   OK, models available: {models}")
    if model not in models:
        print(f"   WARNING: '{model}' is not in that list. Set LLM_MODEL to one of them.")

    print(f"2) Chat with {model}")
    t = time.time()
    r = call(f"{base}/chat/completions", {"model": model, "messages": [{"role": "user", "content": "What is a vector database? One sentence. /no_think"}], "max_tokens": 120}, key)
    text = re.sub(r"<think>.*?</think>", "", r["choices"][0]["message"]["content"], flags=re.S).strip()
    print(f"   OK in {time.time() - t:.1f}s: {text}")

    print("3) JSON output")
    t = time.time()
    r = call(
        f"{base}/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": 'Return ONLY JSON: {"question": "...", "options": ["a","b","c","d"], "answer": "0"} for one easy MCQ about photosynthesis. /no_think'}],
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
        },
        key,
    )
    raw = re.sub(r"<think>.*?</think>", "", r["choices"][0]["message"]["content"], flags=re.S).strip()
    try:
        print(f"   OK in {time.time() - t:.1f}s: {json.loads(raw)}")
    except json.JSONDecodeError:
        print(f"   WARNING: reply was not valid JSON:\n{raw}")

    print(f"4) Embeddings with {emb_model}")
    if not emb_base:
        print("   skipped: EMBEDDING_BASE_URL is empty, so embeddings run on this computer\n"
              "   (needs: pip install -r backend/requirements-local-embeddings.txt)")
    else:
        t = time.time()
        try:
            r = call(f"{emb_base}/embeddings", {"model": emb_model, "input": ["gradient descent updates weights", "how are weights updated?", "the capital of France"]}, emb_key, timeout=60)
            v = [d["embedding"] for d in sorted(r["data"], key=lambda d: d["index"])]
            cos = lambda a, b: sum(x * y for x, y in zip(a, b)) / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))  # noqa: E731
            near, far = cos(v[0], v[1]), cos(v[0], v[2])
            print(f"   OK in {time.time() - t:.1f}s: {len(v[0])} dimensions, related {near:.2f} vs unrelated {far:.2f}" + ("" if near > far else "  WARNING: similarity looks wrong"))
        except Exception as e:
            print(f"   FAIL: {e}\n   This server has no embedding endpoint? Use the LearnWise notebook, or clear EMBEDDING_BASE_URL to embed locally.")

    print("\nAll good. backend/.env should contain:")
    print(f"USE_MOCKS=false\nMOCK_RETRIEVAL=false\nLLM_BASE_URL={base}\nLLM_MODEL={model}")
    if emb_base:
        print(f"EMBEDDING_BASE_URL={emb_base}\nEMBEDDING_MODEL={emb_model}")
    print("Then restart the backend: the sidebar dot turns green.")


if __name__ == "__main__":
    main()
