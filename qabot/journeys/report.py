"""Self-contained local report with actual screenshots and recorded video."""

from __future__ import annotations

import html
import json
from pathlib import Path


def write_report(out: Path, metadata: dict, results: list) -> None:
    data = {**metadata, "results": [r.model_dump(mode="json") for r in results]}
    (out / "results.json").write_text(json.dumps(data, indent=2) + "\n")
    escape = html.escape
    markdown = ["# Journey Results", "", f"Model: {metadata['model']}", ""]
    sections = []
    for result in results:
        markdown.extend(
            [f"## {result.journey.title}: {result.outcome.value.upper()}", "", result.why, ""]
        )
        video = ""
        if result.video:
            relative = Path(result.video).relative_to(out).as_posix()
            video = f'<video controls preload="auto" src="{escape(relative)}"></video>'
            markdown.extend([f"Video: {result.video}", ""])
        steps = []
        for step in result.steps:
            markdown.append(
                f"{step.index + 1}. {step.do} -> {step.see}: {step.outcome.value}. {step.reason}"
            )
            screenshot = ""
            if step.screenshot:
                relative = Path(step.screenshot).relative_to(out).as_posix()
                screenshot = f'<a href="{escape(relative)}"><img loading="lazy" src="{escape(relative)}" alt="Step {step.index + 1} evidence"></a>'
            actions = "\n".join(f"{a.op}: {a.summary} {a.error}" for a in step.actions)
            steps.append(
                f"<details><summary>{step.index + 1}. {escape(step.do)} <b>{step.outcome.value}</b></summary>"
                f"<p>Expected: {escape(step.see)}</p><p>{escape(step.reason)}</p>"
                f"{screenshot}<pre>{escape(actions)}</pre></details>"
            )
        sections.append(
            f"<section><h2>{escape(result.journey.title)} <span>{result.outcome.value.upper()}</span></h2>"
            f"<p>{escape(result.why)}</p>{video}{''.join(steps)}</section>"
        )
    markdown.extend(
        [
            "",
            "## Configuration",
            "",
            "```json",
            json.dumps(metadata.get("configuration", {}), indent=2),
            "```",
        ]
    )
    markdown.extend(
        ["", "## Limitations", *[f"- {item}" for item in metadata.get("limitations", [])]]
    )
    (out / "report.md").write_text("\n".join(markdown) + "\n")
    config = escape(json.dumps(metadata.get("configuration", {}), indent=2))
    limitations = "".join(f"<li>{escape(item)}</li>" for item in metadata.get("limitations", []))
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>qabot Journey Results</title><style>
body{{margin:0;color:#202324;background:#fafafa;font:15px/1.5 system-ui;letter-spacing:0}}main{{max-width:1100px;margin:auto;padding:24px}}
h1{{font-size:26px}}h2{{font-size:19px;display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between}}section{{padding:24px 0;border-top:1px solid #ccc}}
video{{width:100%;aspect-ratio:1.44;background:#111}}img{{width:100%;height:auto}}summary{{cursor:pointer;padding:12px 0}}details{{border-bottom:1px solid #ddd}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;padding:12px}}p,summary{{overflow-wrap:anywhere}}b,span{{color:#555}}
</style><main><h1>qabot Journey Results</h1><p>Model: {escape(metadata["model"])}</p>
{"".join(sections)}<section><h2>Configuration</h2><pre>{config}</pre><h2>Limitations</h2><ul>{limitations}</ul></section></main></html>"""
    (out / "report.html").write_text(document)
