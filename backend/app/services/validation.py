"""Check LLM JSON before it reaches the student.

LLMs sometimes return 3 options, an answer of "B" instead of "1", options
prefixed with "A)", duplicate options, repeated questions or empty fields.
We fix what we can and drop what we can't, rather than crash.
"""
import re

LETTERS = {"a": "0", "b": "1", "c": "2", "d": "3"}
_PREFIX = re.compile(r"^\s*(?:\(?[A-Da-d1-4][).:]|option\s+[A-Da-d1-4][).:]?)\s+")


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def clean_quiz_items(items: list[dict]) -> list[dict]:
    good, seen = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question", "")).strip()
        kind = it.get("type")
        ans = str(it.get("answer", "")).strip()
        if not q or kind not in ("mcq", "short") or not ans or _norm(q) in seen:
            continue
        if kind == "mcq":
            opts = it.get("options") or []
            if not isinstance(opts, list) or len(opts) != 4:
                continue
            opts = [_PREFIX.sub("", str(o)).strip() for o in opts]
            if any(not o for o in opts) or len({_norm(o) for o in opts}) != 4:
                continue  # empty or duplicate options make the question unfair
            ans = _PREFIX.sub("", ans).strip() if len(ans) > 2 else ans.strip(" ).:(")
            ans = LETTERS.get(ans.lower(), ans)
            if ans not in ("0", "1", "2", "3"):
                # maybe the model wrote the option text instead of its index
                match = [i for i, o in enumerate(opts) if _norm(o) == _norm(ans)]
                ans = str(match[0]) if match else ""
            if not ans:
                continue
            it["options"] = opts
        else:
            it["options"] = None
        seen.add(_norm(q))
        it["question"], it["answer"] = q, ans
        it["explanation"] = str(it.get("explanation", "")).strip()
        good.append(it)
    return good


def clean_cards(items: list[dict]) -> list[dict]:
    good, seen = [], set()
    for c in items if isinstance(items, list) else []:
        if not isinstance(c, dict):
            continue
        front, back = str(c.get("front", "")).strip(), str(c.get("back", "")).strip()
        if front and back and _norm(front) not in seen:
            seen.add(_norm(front))
            good.append({**c, "front": front, "back": back})
    return good
