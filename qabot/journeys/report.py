"""Portable local reports with recorded evidence and measured execution timings."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote


def _media_ref(value: str | None, out: Path) -> str | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = out / path
    return path.resolve().relative_to(out.resolve()).as_posix()


def _portable_result(result, out: Path) -> dict:
    data = result.model_dump(mode="json")
    data["video"] = _media_ref(data.get("video"), out)
    for step in data["steps"]:
        step["screenshot"] = _media_ref(step.get("screenshot"), out)
        for action in step["actions"]:
            action["screenshot"] = _media_ref(action.get("screenshot"), out)
    return data


def _timing_text(timing: dict | None) -> str:
    if timing is None:
        return "Timing unavailable"
    return (
        f"Total {timing['total_s']:.2f}s | "
        f"Actor {timing['actor_s']:.2f}s ({timing['actor_calls']} calls) | "
        f"Judge {timing['judge_s']:.2f}s ({timing['judge_calls']} calls) | "
        f"Browser action {timing['action_s']:.2f}s | "
        f"Wait {timing['wait_s']:.2f}s | Evidence/overhead {timing['evidence_s']:.2f}s"
    )


def write_report(out: Path, metadata: dict, results: list) -> None:
    out = Path(out).resolve()
    data = {
        **metadata,
        "artifact_paths": "relative-to-report",
        "results": [_portable_result(result, out) for result in results],
    }
    (out / "results.json").write_text(json.dumps(data, indent=2) + "\n")
    escape = html.escape
    markdown = ["# Journey Results", "", f"Model: {metadata['model']}", ""]
    sections = []
    for number, result in enumerate(data["results"]):
        title = result["journey"]["title"]
        outcome = result["outcome"].upper()
        markdown.extend([f"## {title}: {outcome}", "", result["why"], ""])
        video = ""
        video_id = f"video-{number}"
        if result["video"]:
            url = escape(quote(result["video"], safe="/"))
            video = f'<video id="{video_id}" controls preload="auto" src="{url}"></video>'
            markdown.extend([f"Video: [{result['video']}]({quote(result['video'], safe='/')})", ""])
        steps = []
        measured = [step["timing"] for step in result["steps"] if step.get("timing") is not None]
        if measured:
            totals = {key: sum(t[key] for t in measured) for key in measured[0]}
            summary = f"Measured steps: {len(measured)}/{len(result['steps'])}. {_timing_text(totals)}"
        else:
            summary = "Timing unavailable"
        markdown.extend([summary, ""])
        for step in result["steps"]:
            timing = _timing_text(step.get("timing"))
            markdown.extend([
                f"{step['index'] + 1}. {step['do']} -> {step['see']}: {step['outcome']}. {step['reason']}",
                f"   {timing}",
            ])
            screenshot = ""
            if step["screenshot"]:
                relative = escape(quote(step["screenshot"], safe="/"))
                screenshot = (
                    f'<a href="{relative}"><img loading="lazy" src="{relative}" '
                    f'alt="Step {step["index"] + 1} evidence"></a>'
                )
            chapter = ""
            offset = step.get("started_offset_s")
            if result["video"] and offset is not None:
                label = f"~{int(offset) // 60:02d}:{int(offset) % 60:02d}"
                href = quote(result["video"], safe="/") + f"#t={offset:.2f}"
                chapter = (
                    f'<a class="chapter" href="{escape(href)}" data-video="{video_id}" '
                    f'data-offset="{offset:.2f}" title="Approximate step start in recording">{label}</a> '
                )
                markdown.append(f"   Approximate chapter: [{label}]({href})")
            actions = "\n".join(
                f"{action['op']}: {action['summary']} {action['error']}" for action in step["actions"]
            )
            steps.append(
                f"<details><summary>{chapter}{step['index'] + 1}. {escape(step['do'])} "
                f"<b>{escape(step['outcome'])}</b></summary>"
                f"<p>Expected: {escape(step['see'])}</p><p>{escape(step['reason'])}</p>"
                f'<p class="timing">{escape(timing)}</p>{screenshot}<pre>{escape(actions)}</pre></details>'
            )
        sections.append(
            f"<section><h2>{escape(title)} <span>{escape(outcome)}</span></h2>"
            f"<p>{escape(result['why'])}</p><p class=timing>{escape(summary)}</p>"
            f"{video}{''.join(steps)}</section>"
        )
    notes = (
        "Timings are wall-clock measurements, not provider-internal reasoning time. "
        "Browser action and evidence/driver overhead are measured separately where available; "
        "total includes other orchestration overhead. Approximate chapter offsets start at "
        "journey execution and may differ slightly from recording frames."
    )
    markdown.extend([
        "", "## Timing Notes", "", notes,
        "", "## Configuration", "", "```json",
        json.dumps(metadata.get("configuration", {}), indent=2), "```",
        "", "## Limitations", *[f"- {item}" for item in metadata.get("limitations", [])],
    ])
    (out / "report.md").write_text("\n".join(markdown) + "\n")
    config = escape(json.dumps(metadata.get("configuration", {}), indent=2))
    limitations = "".join(f"<li>{escape(item)}</li>" for item in metadata.get("limitations", []))
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>qabot Journey Results</title><style>
body{{margin:0;color:#202324;background:#fafafa;font:15px/1.5 system-ui;letter-spacing:0}}main{{max-width:1100px;margin:auto;padding:24px}}
h1{{font-size:26px}}h2{{font-size:19px;display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between}}section{{padding:24px 0;border-top:1px solid #ccc}}
video{{width:100%;aspect-ratio:1.44;background:#111}}img{{width:100%;height:auto}}summary{{cursor:pointer;padding:12px 0}}details{{border-bottom:1px solid #ddd}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;padding:12px}}p,summary{{overflow-wrap:anywhere}}b,span{{color:#555}}.timing{{font-size:13px;color:#444}}.chapter{{display:inline-block;min-width:55px;color:#086650}}
</style><main><h1>qabot Journey Results</h1><p>Model: {escape(metadata["model"])}</p>
{"".join(sections)}<section><h2>Timing Notes</h2><p>{escape(notes)}</p><h2>Configuration</h2><pre>{config}</pre><h2>Limitations</h2><ul>{limitations}</ul></section></main>
<script>
document.addEventListener('click', event => {{
  const link = event.target.closest('a[data-video]');
  if (!link) return;
  const video = document.getElementById(link.dataset.video);
  if (!video) return;
  event.preventDefault();
  event.stopPropagation();
  const seek = () => {{ video.currentTime = Number(link.dataset.offset); }};
  if (video.readyState >= 1) seek();
  else {{ video.addEventListener('loadedmetadata', seek, {{once:true}}); video.load(); }}
  video.scrollIntoView({{block:'nearest'}});
}});
</script></html>"""
    (out / "report.html").write_text(document)
