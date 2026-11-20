"""Check LLM JSON before it reaches the student (owner: Sana).

LLMs sometimes return 3 options, an answer of "B" instead of "1", or empty
fields. We fix what we can and drop what we can't, rather than crash.
"""

LETTERS = {"a": "0", "b": "1", "c": "2", "d": "3"}


def clean_quiz_items(items: list[dict]) -> list[dict]:
    good = []
    for it in items:
        q = str(it.get("question", "")).strip()
        kind = it.get("type")
        ans = str(it.get("answer", "")).strip()
        if not q or kind not in ("mcq", "short") or not ans:
            continue
        if kind == "mcq":
            opts = it.get("options") or []
            if len(opts) != 4:
                continue
            ans = LETTERS.get(ans.lower(), ans)
            if ans not in ("0", "1", "2", "3"):
                # maybe the model wrote the option text instead of its index
                ans = str(opts.index(ans)) if ans in opts else ""
            if not ans:
                continue
            it["options"] = [str(o) for o in opts]
        else:
            it["options"] = None
        it["question"], it["answer"] = q, ans
        it["explanation"] = str(it.get("explanation", "")).strip()
        good.append(it)
    return good


def clean_cards(items: list[dict]) -> list[dict]:
    return [c for c in items if str(c.get("front", "")).strip() and str(c.get("back", "")).strip()]
