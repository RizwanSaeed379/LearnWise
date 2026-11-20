"""Check that your laptop can reach the LLM running on Kaggle (or Ollama / Groq).

No packages needed, plain Python 3:

    python kaggle/test_connection.py https://something.trycloudflare.com/v1
    python kaggle/test_connection.py            # reads LLM_BASE_URL from backend/.env

It checks three things: the server answers, the model replies, and it can return clean JSON
(which notes/quiz/flashcards depend on).
"""
import json
import pathlib
import re
import sys
import time
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
    model = sys.argv[2] if len(sys.argv) > 2 else env.get("LLM_MODEL", "qwen3:8b")
    key = env.get("LLM_API_KEY", "not-needed")
    if not base:
        sys.exit("Give the URL: python kaggle/test_connection.py https://xxxx.trycloudflare.com/v1")
    if not base.endswith("/v1"):
        print("note: URL usually ends with /v1, e.g. https://xxxx.trycloudflare.com/v1")

    print(f"1) GET {base}/models")
    try:
        models = [m["id"] for m in call(f"{base}/models", key=key, timeout=15)["data"]]
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

    print("\nAll good. Put these in backend/.env:")
    print(f"LLM_BASE_URL={base}\nLLM_MODEL={model}\nUSE_MOCKS=false\nMOCK_RETRIEVAL=true   # until the real retrieval pipeline is finished")


if __name__ == "__main__":
    main()
