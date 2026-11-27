"""Runtime check of a generated answer against the passages it cites.

For each sentence of the answer:
  * every [S#] label must point to a passage that was actually in the prompt (1..len(sources));
  * the sentence is "supported" when at least VERIFY_SENTENCE_SUPPORT of its content words appear in
    the passages it cites (all passages, if it cites none). Same idea as supported() in eval/run_eval.py.
The answer passes when it has no out-of-range label, cites at least one passage, and the share of
supported sentences is at least VERIFY_MIN_SUPPORT.

A cheap lexical proxy, not entailment: it catches invented facts and wrong labels, not subtle errors.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas import SourceRef
from app.services.text import sentences, support

_LABEL = re.compile(r"\[S(\d+)\]")


@dataclass
class Verdict:
    ok: bool
    support: float  # share of sentences supported by their cited passages (0-1)
    sentences: int
    unsupported: list[str] = field(default_factory=list)
    bad_labels: list[int] = field(default_factory=list)  # labels with no matching passage, e.g. [S7] with 5 sources
    cited: bool = False  # at least one valid [S#]

    def problems(self) -> str:
        out = []
        if self.bad_labels:
            out.append("cites passages that do not exist: " + ", ".join(f"[S{n}]" for n in self.bad_labels))
        if not self.cited:
            out.append("has no [S#] citation")
        if self.unsupported:
            out.append("has sentences not stated in their cited passage: " + " | ".join(self.unsupported[:3]))
        return "; ".join(out)


def verify_answer(answer: str, sources: list[SourceRef], sentence_need: float = 0.5, min_support: float = 0.75) -> Verdict:
    n = len(sources)
    sents = sentences(answer)
    bad: set[int] = set()
    unsupported, good, cited = [], 0, False
    for sent in sents:
        labels = [int(x) for x in _LABEL.findall(sent)]
        bad |= {x for x in labels if not 1 <= x <= n}
        valid = [x for x in labels if 1 <= x <= n]
        cited = cited or bool(valid)
        passages = [sources[x - 1].snippet for x in valid] or [s.snippet for s in sources]
        if support(sent, passages) >= sentence_need:
            good += 1
        else:
            unsupported.append(sent)
    # labels can also sit outside a sentence the splitter keeps (e.g. a bare "[S9]")
    bad |= {int(x) for x in _LABEL.findall(answer) if not 1 <= int(x) <= n}
    cited = cited or any(1 <= int(x) <= n for x in _LABEL.findall(answer))
    share = good / len(sents) if sents else 0.0
    ok = not bad and cited and bool(sents) and share >= min_support
    return Verdict(ok=ok, support=round(share, 3), sentences=len(sents), unsupported=unsupported, bad_labels=sorted(bad), cited=cited)


def strip_bad_labels(answer: str, n_sources: int) -> str:
    """Remove [S#] labels that point past the retrieved passages, so the UI never shows a dead citation."""
    out = _LABEL.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_sources else "", answer)
    return re.sub(r"\s+([.,;!?])", r"\1", re.sub(r"[ \t]{2,}", " ", out)).strip()
