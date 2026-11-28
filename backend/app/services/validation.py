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


MAX_DEPTH = 3
MAX_LINKS = 8
# link labels that say nothing about HOW two ideas relate; such links only add clutter
_VAGUE_LINKS = {"", "related", "related to", "relates to", "is related to", "linked to", "connected to", "connects to",
                "associated with", "see also", "link", "relation", "relationship"}


def _short(s, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def clean_mindmap(data: dict, max_nodes: int, fallback_title: str = "Mind map") -> dict:
    """Turn the model's mind map into a valid tree.

    Fixes: missing/duplicate ids, duplicate labels (merged, their children kept), several roots or none,
    parents that don't exist, cycles, too many levels, too many nodes (kept breadth-first so the tree stays
    connected), and links that point nowhere, repeat a tree edge or link a node to itself.
    Returns {"title", "nodes": [{id, label, summary, parent, level, source}], "links": [{from, to, label}]}
    with ids renumbered n1, n2 ... in breadth-first order. Fewer than 2 nodes means nothing usable.
    """
    data = data if isinstance(data, dict) else {}
    title = _short(data.get("title"), 80) or fallback_title
    raw = data.get("nodes") if isinstance(data.get("nodes"), list) else []

    nodes: dict[str, dict] = {}   # id -> node, in the model's order
    alias: dict[str, str] = {}    # any id the model used -> the id we kept
    by_label: dict[str, str] = {}
    for i, n in enumerate(raw):
        if not isinstance(n, dict):
            continue
        label = _short(n.get("label"), 60)
        nid = str(n.get("id") or "").strip() or f"auto{i}"
        if not label:
            continue
        key = _norm(label)
        if key in by_label:          # same concept twice: merge into the first one
            alias.setdefault(nid, by_label[key])
            continue
        if nid in nodes:             # id reused for a different concept
            nid = f"{nid}_{i}"
        raw_parent = n.get("parent", n.get("parent_id"))
        nodes[nid] = {"id": nid, "label": label, "summary": _short(n.get("summary"), 240),
                      "parent": None if raw_parent in (None, "", "null") else str(raw_parent).strip(), "source": n.get("source")}
        alias[nid] = nid
        by_label[key] = nid
    if not nodes:
        return {"title": title, "nodes": [], "links": []}

    for n in nodes.values():
        if n["parent"] is not None:
            n["parent"] = alias.get(n["parent"], "?")  # "?" = unknown parent, attached to the root below

    # one root: the first node the model gave no parent, or a new node named after the title
    roots = [n for n in nodes.values() if n["parent"] is None]
    if roots:
        root = roots[0]
    else:
        root = {"id": "root", "label": _short(title, 60), "summary": "", "parent": None, "source": None}
        nodes = {"root": root, **nodes}
    for n in nodes.values():
        if n is not root and n["parent"] in (None, "?", n["id"]):
            n["parent"] = root["id"]

    # cycles: a chain that never reaches the root is re-attached to it
    for n in nodes.values():
        seen, cur = set(), n
        while cur["parent"] is not None and cur["id"] not in seen:
            seen.add(cur["id"])
            cur = nodes[cur["parent"]]
        if cur is not root:
            n["parent"] = root["id"]

    # breadth-first from the root: gives levels, drops nodes too deep, keeps the first max_nodes
    children: dict[str, list[str]] = {}
    for n in nodes.values():
        if n["parent"] is not None:
            children.setdefault(n["parent"], []).append(n["id"])
    order, level, queue = [], {root["id"]: 0}, [root["id"]]
    while queue and len(order) < max_nodes:
        nid = queue.pop(0)
        order.append(nid)
        if level[nid] < MAX_DEPTH:
            for c in children.get(nid, []):
                level[c] = level[nid] + 1
                queue.append(c)
    if len(order) < 2:
        return {"title": title, "nodes": [], "links": []}

    new_id = {old: f"n{i + 1}" for i, old in enumerate(order)}
    out_nodes = [{**nodes[old], "id": new_id[old], "parent": new_id.get(nodes[old]["parent"]), "level": level[old]} for old in order]

    edges = {frozenset((n["id"], n["parent"])) for n in out_nodes if n["parent"]}
    parent_of = {n["id"]: n["parent"] for n in out_nodes}

    def ancestors(nid):
        out = set()
        while parent_of.get(nid):
            nid = parent_of[nid]
            out.add(nid)
        return out

    links, seen_pairs = [], set()
    for l in data.get("links") if isinstance(data.get("links"), list) else []:
        if not isinstance(l, dict) or len(links) >= MAX_LINKS:
            continue
        a = new_id.get(alias.get(str(l.get("from", l.get("from_id", ""))).strip(), ""))
        b = new_id.get(alias.get(str(l.get("to", l.get("to_id", ""))).strip(), ""))
        pair = frozenset((a, b))
        label = _short(l.get("label"), 40)
        if not a or not b or a == b or pair in edges or pair in seen_pairs or _norm(label) in _VAGUE_LINKS:
            continue
        if a in ancestors(b) or b in ancestors(a):
            continue  # already connected through the tree
        seen_pairs.add(pair)
        links.append({"from": a, "to": b, "label": label})
    return {"title": title, "nodes": out_nodes, "links": links}
