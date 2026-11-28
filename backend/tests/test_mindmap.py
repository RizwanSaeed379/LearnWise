"""Mind map: mock mode, the real path with a fake LLM, and the validator that turns model JSON into a tree."""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.prompts import templates
from app.services.llm import get_llm
from app.services.validation import clean_mindmap


def _is_tree(nodes, root_id):
    ids = {n["node_id"] for n in nodes}
    roots = [n for n in nodes if n["parent_id"] is None]
    assert [r["node_id"] for r in roots] == [root_id]
    for n in nodes:
        assert n["parent_id"] is None or n["parent_id"] in ids
        assert 0 <= n["level"] <= 3


# ---- mock mode ----
@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setattr(get_settings(), "use_mocks", True)
    return TestClient(app)


def test_mock_whole_document(mocked):
    body = mocked.post("/api/mindmap", json={}).json()
    assert body["topic"] is None and body["root_id"] == "n1" and len(body["nodes"]) >= 10 and body["links"]
    _is_tree(body["nodes"], body["root_id"])


def test_mock_topic_and_limit(mocked):
    body = mocked.post("/api/mindmap", json={"topic": "Backpropagation", "max_nodes": 6}).json()
    assert body["nodes"][0]["label"] == "Backpropagation" and len(body["nodes"]) <= 6
    assert [n["label"] for n in body["nodes"]].count("Backpropagation") == 1
    _is_tree(body["nodes"], body["root_id"])


def test_max_nodes_is_validated(mocked):
    r = mocked.post("/api/mindmap", json={"max_nodes": 2})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


# ---- real path, fake LLM ----
class FakeMindMapLLM:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    async def chat_json(self, messages, **kw):
        self.prompts.append(messages[-1]["content"])
        return self.reply


GOOD = {
    "title": "Backprop",
    "nodes": [
        {"id": "a", "label": "Backpropagation", "parent": None, "summary": "Uses the chain rule [S1].", "source": "S1"},
        {"id": "b", "label": "Chain rule", "parent": "a", "summary": "Derivatives multiplied [S1].", "source": "S1"},
        {"id": "c", "label": "Weight update", "parent": "a", "summary": "w = w - lr * dL/dw [S2].", "source": "S2"},
    ],
    "links": [{"from": "b", "to": "c", "label": "feeds"}, {"from": "a", "to": "b", "label": "tree edge, dropped"}],
}


@pytest.fixture
def real(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "use_mocks", False)
    monkeypatch.setattr(s, "mock_retrieval", True)

    def use(reply):
        llm = FakeMindMapLLM(reply)
        app.dependency_overrides[get_llm] = lambda: llm
        return TestClient(app), llm

    yield use
    app.dependency_overrides.clear()


def test_real_path_maps_sources_and_links(real):
    c, llm = real(GOOD)
    body = c.post("/api/mindmap", json={"topic": "Backprop"}).json()
    assert [n["label"] for n in body["nodes"]] == ["Backpropagation", "Chain rule", "Weight update"]
    assert body["nodes"][2]["source"]["page"] == 8  # S2 -> second mock passage (page 8)
    assert body["links"] == [{"from_id": "n2", "to_id": "n3", "label": "feeds"}]
    assert "TOPIC: Backprop" in llm.prompts[0]


def test_real_path_whole_document_prompt(real):
    c, llm = real(GOOD)
    assert c.post("/api/mindmap", json={"topic": "  "}).status_code == 200
    assert "WHOLE material" in llm.prompts[0]


def test_unusable_model_reply_is_502(real):
    c, _ = real({"nodes": [{"id": "x", "label": "Only one"}]})
    r = c.post("/api/mindmap", json={"topic": "Backprop"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "llm_error"


# ---- validator ----
def test_clean_fixes_roots_parents_cycles_duplicates():
    data = {
        "title": "T",
        "nodes": [
            {"id": "1", "label": "Root", "parent": None},
            {"id": "2", "label": "Second root", "parent": None},      # extra root -> child of Root
            {"id": "3", "label": "Orphan", "parent": "missing"},      # unknown parent -> child of Root
            {"id": "4", "label": "Loop A", "parent": "5"},            # 4 <-> 5 cycle -> re-attached
            {"id": "5", "label": "Loop B", "parent": "4"},
            {"id": "6", "label": "root", "parent": "1"},              # duplicate label -> merged
            {"id": "7", "label": "Kid of dup", "parent": "6"},        # ... its child goes to the kept node
            {"id": "8", "label": "", "parent": "1"},                  # empty label dropped
            "not a node",
        ],
        "links": [{"from": "3", "to": "2", "label": "uses"}, {"from": "3", "to": "3", "label": "uses"},
                  {"from": "3", "to": "nope", "label": "uses"}, {"from": "2", "to": "3", "label": "uses"}],
    }
    m = clean_mindmap(data, 20)
    labels = {n["label"]: n for n in m["nodes"]}
    assert m["nodes"][0]["label"] == "Root" and m["nodes"][0]["parent"] is None
    assert set(labels) == {"Root", "Second root", "Orphan", "Loop A", "Loop B", "Kid of dup"}
    assert labels["Kid of dup"]["parent"] == labels["Root"]["id"]
    assert all(n["parent"] for n in m["nodes"][1:])
    assert len(m["links"]) == 1  # self-link, unknown node and the reversed duplicate are dropped


def test_clean_limits_depth_and_count_breadth_first():
    chain = [{"id": str(i), "label": f"L{i}", "parent": str(i - 1) if i else None} for i in range(6)]
    m = clean_mindmap({"nodes": chain}, 20)
    assert [n["level"] for n in m["nodes"]] == [0, 1, 2, 3]  # levels 4 and 5 dropped

    wide = [{"id": "r", "label": "R", "parent": None}] + [{"id": f"c{i}", "label": f"C{i}", "parent": "r"} for i in range(10)]
    m = clean_mindmap({"nodes": wide}, 5)
    assert len(m["nodes"]) == 5 and all(n["parent"] == "n1" for n in m["nodes"][1:])


def test_clean_creates_root_from_title_when_every_node_has_a_parent():
    m = clean_mindmap({"title": "Lecture", "nodes": [{"id": "a", "label": "A", "parent": "b"}, {"id": "b", "label": "B", "parent": "a"}]}, 10)
    assert m["nodes"][0]["label"] == "Lecture" and len(m["nodes"]) == 3


def test_clean_handles_garbage():
    assert clean_mindmap("nonsense", 10)["nodes"] == []
    assert clean_mindmap({"nodes": [{"label": "Alone"}]}, 10)["nodes"] == []


def test_prompt_mentions_limits_and_topics():
    p = templates.mindmap_prompt(None, 12, "<documents>x</documents>", ["Perceptron", "Dropout"])[-1]["content"]
    assert "at most 12 nodes" in p and "Perceptron, Dropout" in p and "WHOLE material" in p


def test_clean_drops_vague_and_redundant_links():
    data = {
        "nodes": [
            {"id": "r", "label": "Photosynthesis", "parent": None},
            {"id": "a", "label": "Light reactions", "parent": "r"},
            {"id": "a1", "label": "Photolysis", "parent": "a"},
            {"id": "b", "label": "Calvin cycle", "parent": "r"},
            {"id": "c", "label": "Light intensity", "parent": "r"},
        ],
        "links": [
            {"from": "a", "to": "b", "label": "supplies ATP to"},     # kept: specific, other branch
            {"from": "c", "to": "a", "label": "Related to"},          # vague
            {"from": "c", "to": "b", "label": ""},                    # no label
            {"from": "a1", "to": "r", "label": "is part of"},         # ancestor: already shown by the tree
            {"from": "c", "to": "a1", "label": "speeds up"},          # kept
        ],
    }
    links = clean_mindmap(data, 20)["links"]
    assert [l["label"] for l in links] == ["supplies ATP to", "speeds up"]


def test_prompt_asks_for_concepts_not_document_parts():
    p = templates.mindmap_prompt("Photosynthesis", 18, "<documents>x</documents>")[-1]["content"]
    assert "CONCEPTS" in p and "review questions" in p and "related to" in p
