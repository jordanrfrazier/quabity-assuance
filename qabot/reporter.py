"""Report rendering: the one artifact of a run a human actually reads.

The report is where the bot's honesty has to be structural rather than tonal, so
two rules live here as code and not as prompt instructions:

  1. BLOCKED is neither a pass nor a failure. Blocked work is lifted out of the
     severity sections entirely, given its own prominent section, and never
     influences the exit code. A bot that renders "I could not test this" as a
     green check has lied; one that renders it as a red X has cried wolf. Both
     get uninstalled in week two.

  2. Everything the run did not cover -- truncated for budget, anchored to code
     that no longer resolves -- is printed. Truncation must never read as coverage.

Every severity is printed next to what it *means in terms of provenance*, because
the distance between "a human said this must hold and it does not" and "we read
your code and guessed" is the entire product. A reader who cannot tell those apart
at a glance has been given a pile of noise with a logo on it.

For the same reason, findings from the intrinsic oracles are printed in their own
sections rather than under a severity heading that explains itself in terms of
provenance, which would be false of them. There are two, and the distance between
them is the point: what the application *declared* -- a 5xx, an uncaught exception,
a stack trace -- leads the report, because nothing was inferred and it cannot be our
misreading; what the application merely *logged* closes it, because calling a console
error a defect is a reading, and this report does not make readings it cannot support.
A reader must never meet the second under a sentence promising the first.
"""

from __future__ import annotations

from qabot.intrinsics import declares_failure
from qabot.models import (
    Finding,
    OpenQuestion,
    Outcome,
    Provenance,
    RunReport,
    Severity,
    WorkflowResult,
)

#: Loudest first. A reader scanning the top of the comment sees the confirmed
#: breakage before the speculation, never the other way round.
SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.BUG,
    Severity.REGRESSION,
    Severity.CHANGE,
    Severity.QUESTION,
)

SEVERITY_NOUN: dict[Severity, str] = {
    Severity.BUG: "bug",
    Severity.REGRESSION: "regression",
    Severity.CHANGE: "change",
    Severity.QUESTION: "question",
}

#: What each severity is *allowed to claim*, phrased in terms of where the
#: expectation came from. This is the provenance cap in `models.PROVENANCE_CAP`,
#: restated for a human who has never heard the word "provenance".
SEVERITY_MEANING: dict[Severity, str] = {
    Severity.BUG: "a human confirmed this behavior; it is broken.",
    Severity.REGRESSION: "an earlier run observed this working; it no longer works.",
    Severity.CHANGE: "your existing tests implied this; did you mean to change it?",
    Severity.QUESTION: (
        "inferred from reading the code and never confirmed -- this may be our "
        "misreading rather than your bug."
    ),
}

#: Headings for findings no expectation produced. Not severities: these are not graded,
#: and each heading has to say in words a reader already has what its tier claims.
INTRINSIC_HEADING = "Errors the application reported about itself"

INTRINSIC_MEANING = (
    "the application declared these itself -- a server error, an uncaught exception, "
    "a stack trace in the response. Nothing here was inferred from your code or your "
    "tests, so no provenance cap applies and there is no expectation of ours that "
    "could be a misreading of yours."
)

NOTICED_HEADING = "Noticed, but not called a defect"

NOTICED_MEANING = (
    "the application logged these itself, but whether they are defects is a reading "
    "we will not make: an app logs expected conditions at error level, and a "
    "cancelled request is usually the app cancelling it. Reported so that nothing is "
    "silent, and held at QUESTION so that nothing here claims more than it can."
)

#: Printed on an intrinsic finding in place of a provenance line, since it has none.
#: One per tier, because the tiers make different claims and one sentence cannot make
#: both without lying about one of them.
INTRINSIC_LABEL = "the application reported this itself; nothing was inferred, so no provenance cap"

NOTICED_LABEL = (
    "the application logged this itself; whether it is a defect is a reading we will not make"
)

PROVENANCE_LABEL: dict[Provenance, str] = {
    Provenance.HUMAN_CONFIRMED: "a human confirmed this expectation",
    Provenance.OBSERVED_IN_RUN: "observed working in an earlier run",
    Provenance.INFERRED_FROM_TEST: "derived from an existing test's assertion",
    Provenance.INFERRED_FROM_CODE: "inferred from reading the code; never confirmed",
}

#: Only these can fail a build, and only when the caller opts in. Everything below
#: REGRESSION rests on an inference the customer never agreed to.
BLOCKING_SEVERITIES: frozenset[Severity] = frozenset({Severity.BUG, Severity.REGRESSION})


def _plural(noun: str, count: int) -> str:
    return noun if count == 1 else f"{noun}s"


def reported_findings(report: RunReport) -> list[Finding]:
    """Findings that say something about the app.

    A BLOCKED finding is a fact about the *run*, not about the code, so it is not
    a finding for reporting purposes. This single filter is what keeps rule 1 from
    depending on anybody's good intentions downstream.
    """
    return [f for f in report.findings if f.outcome is not Outcome.BLOCKED]


def blocked_results(report: RunReport) -> list[WorkflowResult]:
    """Workflows that were not (fully) exercised: blocked outright, or blocked on at
    least one step or expectation while the rest of the workflow ran.

    A blocked *step* counts even when the workflow's own outcome is FAIL, because a
    workflow can both fail and be incomplete -- an app that 500s often drops the
    connection, and the steps after it never happen. Keying this section off the
    workflow outcome alone would let that failure swallow the gap it caused, and rule
    1 does not have an exception for "we found something worse elsewhere".
    """
    return [
        r
        for r in report.results
        if r.outcome is Outcome.BLOCKED
        or any(s.outcome is Outcome.BLOCKED for s in r.steps)
        or any(f.outcome is Outcome.BLOCKED for f in r.findings)
    ]


def summary_line(report: RunReport) -> str:
    """One line: what we found, what we could not test, what we never reached.

    The last two counts are printed even when zero. "0 could not be tested" is a
    coverage claim worth making explicitly; a missing section is not.
    """
    findings = reported_findings(report)
    counts = {s: sum(1 for f in findings if f.severity is s) for s in SEVERITY_ORDER}
    breakdown = ", ".join(
        f"{counts[s]} {_plural(SEVERITY_NOUN[s], counts[s])}" for s in SEVERITY_ORDER
    )
    blocked = len(blocked_results(report))
    skipped = len(report.skipped_for_budget)
    return (
        f"{len(findings)} {_plural('finding', len(findings))} ({breakdown})"
        f" | {blocked} could not be tested"
        f" | {skipped} not tested (budget)"
    )


NOTHING_EXERCISED = (
    "**This run verified nothing.** No workflow in the knowledge base was implicated by "
    "this diff, or none survived to run, so none was exercised. That is not a pass: it is "
    "the absence of evidence either way, and it usually means the knowledge base does not "
    "reach the code that changed rather than that the change was safe."
)


def _nothing_exercised_section(report: RunReport) -> list[str]:
    """Say so, first and loudest, when the run selected no workflow at all.

    A report with no findings reads as a clean bill of health, and for an empty
    selection that reading is false -- the most expensive mistake this tool can make,
    because it is the one that gets believed. The rest of the report is unchanged and
    still accurate; what it lacked was the sentence that stops a reader trusting it.
    """
    if report.results:
        return []
    return [NOTHING_EXERCISED, ""]


def _render_finding(finding: Finding) -> list[str]:
    lines = [
        f"**{finding.workflow_name}** (`{finding.workflow_id}`)",
        "",
        f"> {finding.statement}",
        "",
    ]
    if finding.detail:
        lines.append(f"- Detail: {finding.detail}")
    if finding.provenance is not None:
        lines.append(
            f"- Provenance: `{finding.provenance.value}` -- {PROVENANCE_LABEL[finding.provenance]}"
        )
    if finding.oracle is not None:
        label = INTRINSIC_LABEL if declares_failure(finding) else NOTICED_LABEL
        lines.append(f"- Oracle: `{finding.oracle}` -- {label}")
    if finding.repro:
        lines.append("- Repro:")
        lines.extend(f"  {i}. {step}" for i, step in enumerate(finding.repro, 1))
    lines.append("")
    return lines


def _findings_section(report: RunReport) -> list[str]:
    findings = reported_findings(report)
    if not findings:
        if not report.results:
            return [
                "### Findings",
                "",
                "None were looked for. Nothing was exercised, so nothing was checked.",
                "",
            ]
        return [
            "### Findings",
            "",
            "None. Every expectation that could be checked held.",
            "",
        ]

    lines = ["### Findings", ""]

    # The whole report reads loudest first, and that ordering decides where the two
    # intrinsic tiers go rather than any wish to keep them adjacent. What the app
    # declared opens the report: it is the most certain thing in it, and no inference
    # of ours stands behind it. What the app merely logged closes it, below even the
    # graded questions: it is the least certain thing in it. Neither belongs under a
    # severity heading, which explains itself in terms of a provenance they do not have.
    declared = [f for f in findings if declares_failure(f)]
    noticed = [f for f in findings if f.oracle is not None and not declares_failure(f)]

    if declared:
        lines += [
            f"#### {INTRINSIC_HEADING} ({len(declared)})",
            "",
            f"_{INTRINSIC_MEANING}_",
            "",
        ]
        for finding in declared:
            lines += _render_finding(finding)

    for severity in SEVERITY_ORDER:
        group = [f for f in findings if f.severity is severity and f.oracle is None]
        if not group:
            continue
        lines += [
            f"#### {SEVERITY_NOUN[severity].title()}s ({len(group)})",
            "",
            f"_{severity.name} = {SEVERITY_MEANING[severity]}_",
            "",
        ]
        for finding in group:
            lines += _render_finding(finding)

    if noticed:
        lines += [
            f"#### {NOTICED_HEADING} ({len(noticed)})",
            "",
            f"_{NOTICED_MEANING}_",
            "",
        ]
        for finding in noticed:
            lines += _render_finding(finding)
    return lines


def _blocked_section(report: RunReport) -> list[str]:
    """Always rendered, even when empty: a reader who never sees this section has
    no way to know it exists, and so no way to know what the run left uncovered."""
    blocked = blocked_results(report)
    lines = ["### Could not test", ""]
    if not blocked:
        lines += ["None. Every selected workflow was exercised.", ""]
        return lines

    lines += [
        (
            "Not a pass and not a failure. These were never exercised, so this run is "
            "evidence of nothing about them either way."
        ),
        "",
    ]
    for result in blocked:
        lines.append(f"- **{result.workflow_name}** (`{result.workflow_id}`)")
        reasons = [
            f"  - step `{s.intent}` -- {s.detail}"
            for s in result.steps
            if s.outcome is Outcome.BLOCKED
        ]
        reasons += [
            f'  - expectation "{f.statement}" -- {f.detail}'
            for f in result.findings
            if f.outcome is Outcome.BLOCKED
        ]
        lines.extend(reasons or ["  - reason not recorded"])
    lines.append("")
    return lines


def _limitations_section(report: RunReport) -> list[str]:
    """Conditions the run could not establish about itself.

    Sits next to "could not test" because it is the same kind of statement -- a fact
    about the run rather than about the code -- and it is printed for the same
    reason: a caveat the driver knows and the reader never sees is a caveat nobody
    actually made.
    """
    if not report.limitations:
        return []
    return [
        "### Limitations of this run",
        "",
        "These conditions could not be established, and they qualify every result above.",
        "",
        *(f"- {limitation}" for limitation in report.limitations),
        "",
    ]


def _budget_section(report: RunReport) -> list[str]:
    if not report.skipped_for_budget:
        return []
    return [
        "### Not tested (budget)",
        "",
        (
            "The run was truncated before reaching these. They were not checked, and "
            "their absence above is not a clean bill of health."
        ),
        "",
        *(f"- `{workflow_id}`" for workflow_id in report.skipped_for_budget),
        "",
    ]


def _stale_section(report: RunReport) -> list[str]:
    if not report.stale_workflows:
        return []
    return [
        "### Stale knowledge",
        "",
        (
            "These workflows' code anchors no longer resolve -- what we know about them "
            "points at code that has moved or been deleted. Treat their results as "
            "suspect until the knowledge base is re-anchored."
        ),
        "",
        *(f"- `{workflow_id}`" for workflow_id in report.stale_workflows),
        "",
    ]


def _render_question(question: OpenQuestion) -> list[str]:
    marker = "**[blocking]** " if question.blocking else ""
    lines = [f"- {marker}{question.question}"]
    if question.workflow_id:
        lines.append(f"  - workflow: `{question.workflow_id}`")
    if question.trigger:
        lines.append(f"  - raised by: {question.trigger}")
    if question.candidates:
        lines.append("  - candidates: " + ", ".join(f"`{c}`" for c in question.candidates))
    return lines


def _questions_section(report: RunReport) -> list[str]:
    if not report.open_questions:
        return []
    lines = [
        "### Open questions",
        "",
        (
            "Answering one of these raises an expectation's provenance, which raises how "
            "loudly a future violation of it may be reported. This is the queue."
        ),
        "",
    ]
    for question in report.open_questions:
        lines += _render_question(question)
    lines.append("")
    return lines


def render_markdown(report: RunReport) -> str:
    """The PR comment."""
    lines = [
        f"## qabot -- {report.repo}",
        "",
        f"`{report.base_ref}` -> `{report.head_ref}`",
        "",
        summary_line(report),
        "",
        *_nothing_exercised_section(report),
        *_findings_section(report),
        *_blocked_section(report),
        *_limitations_section(report),
        *_budget_section(report),
        *_stale_section(report),
        *_questions_section(report),
    ]
    return "\n".join(lines).rstrip() + "\n"


def exit_code(report: RunReport, blocking: bool = False) -> int:
    """Advisory by default: a QA bot that blocks merges on day one gets uninstalled
    on day two, and a bot nobody trusts to be right cannot be allowed to gate.

    Only BUG and REGRESSION can fail a build, and only when the caller asks. CHANGE
    and QUESTION rest on inferences the customer never agreed to, and BLOCKED is
    not a failure at all.
    """
    if not blocking:
        return 0
    failing = any(f.severity in BLOCKING_SEVERITIES for f in reported_findings(report))
    return 1 if failing else 0
