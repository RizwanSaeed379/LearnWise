"""Smoke test: the evaluation script runs end to end in offline mode (own process, so settings are fresh)."""
import json
import pathlib
import subprocess
import sys

import pytest

pytest.importorskip("pymupdf")
pytest.importorskip("pptx")


def test_eval_offline_runs(tmp_path):
    root = pathlib.Path(__file__).resolve().parents[2]
    r = subprocess.run([sys.executable, str(root / "eval" / "run_eval.py"), "--offline", "--out", str(tmp_path)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    res = json.loads((tmp_path / "results_offline.json").read_text())
    assert res["retrieval"]["questions"] == 17 and res["retrieval"]["mrr"] > 0.5
    assert res["grounding"]["correct_refusal_pct"] == 100.0
    assert res["exam_marking"]["mcq_self_check_100pct"] is True
