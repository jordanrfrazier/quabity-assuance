"""Markdown a tester can follow. Every step keeps its `do` and `see`, so the report is
also the journey, re-runnable by hand."""

from __future__ import annotations

from qabot.models import Severity
from spikes.journeys.evidence import Evidence
from spikes.journeys.models import JourneyResult, StepOutcome

_MARK = {
    StepOutcome.HELD: "✓",
    StepOutcome.FAILED: "✗",
    StepOutcome.BLOCKED: "–",
    StepOutcome.NOT_REACHED: "○",
}


def _header(evidence: Evidence | None, caps: dict | None) -> list[str]:
    out: list[str] = []
    if evidence is not None:
        truncated = " (diff truncated)" if evidence.diff_truncated else ""
        out += [
            f"Change: `{evidence.base}..{evidence.head}`{truncated}",
            f"Settings touched: {', '.join(evidence.settings_names) or 'none'}",
            "",
        ]
    if caps:
        out += ["Caps: " + ", ".join(f"{k}={v}" for k, v in caps.items()), ""]
    return out


def _journey_block(r: JourneyResult) -> list[str]:
    j = r.journey
    story = (
        f"As a {j.persona}, I want {j.goal} because {j.because}." if j.goal else f"*{j.persona}*"
    )
    out = [f"## {j.title}", "", story, ""]
    if j.preconditions.settings or j.preconditions.state:
        pre = [f"{k}={v}" for k, v in j.preconditions.settings.items()] + j.preconditions.state
        out += ["Preconditions: " + "; ".join(pre), ""]
    if j.traces_to:
        out += [f"Traces to: {j.traces_to}", ""]
    if r.video:
        out += [f"Video of this walk: `{r.video}`", ""]
    for s in r.steps:
        line = f"{s.index + 1}. {_MARK[s.outcome]} **{s.do}** — see: {s.see}"
        if s.reason and s.outcome is not StepOutcome.HELD:
            line += f"  \n   {s.outcome.value}: {s.reason}"
        if s.screenshot:
            line += f"  \n   screenshot: `{s.screenshot}`"
        out.append(line)
        declared = [
            f.detail for f in s.findings if f.oracle is not None and f.severity is Severity.BUG
        ]
        inferred = [f.detail for f in s.findings if f.oracle is None]
        if declared:
            out.append("   - The app said (BUG): " + "; ".join(declared))
        if inferred:
            out.append("   - We inferred (QUESTION): " + "; ".join(inferred))
    verdict = f"**Outcome: {r.outcome.value.upper()}**" + (f" — {r.why}" if r.why else "")
    return [*out, "", verdict, ""]


def render(
    results: list[JourneyResult], evidence: Evidence | None = None, caps: dict | None = None
) -> str:
    out: list[str] = ["# User journeys — walked", ""]
    out += _header(evidence, caps)
    out += ["| Journey | Outcome |", "|---|---|"]
    out += [f"| {r.journey.title} | {r.outcome.value.upper()} |" for r in results]
    out.append("")
    for r in results:
        out += _journey_block(r)
    blocked = [
        (r.journey.title, s)
        for r in results
        for s in r.steps
        if s.outcome in (StepOutcome.BLOCKED, StepOutcome.NOT_REACHED)
    ]
    out += ["## What this run could not check", ""]
    if not blocked:
        out.append("Every step of every journey was walked and judged.")
    for title, s in blocked:
        why = s.reason or "an earlier step did not hold"
        out.append(f"- {title}, step {s.index + 1} ({_MARK[s.outcome]} {s.outcome.value}): {why}")
    return "\n".join(out) + "\n"
