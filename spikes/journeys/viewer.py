"""One HTML page for a set of walks: the journeys as stories, each step marked per build,
the screenshot after each step, and the recording when there is one.

    uv run python -m spikes.journeys.viewer --title "Langflow PR #14913" \\
        --run fixed=qa-artifacts/journeys-2026-09-05/launch_fixed \\
        --run broken=qa-artifacts/journeys-2026-09-05/launch_broken \\
        --out qa-artifacts/journeys-2026-09-05/journeys.html
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

MARK = {"held": "✓", "failed": "✗", "blocked": "–", "not_reached": "○"}

STYLE = """
:root{--paper:#f6f8f9;--surface:#eceff2;--rule:#c9d1d8;--ink:#17202a;--body:#33404d;
--muted:#67747f;--accent:#35507a;--true:#2c6a4a;--false:#8f2f36;--hold:#7a5a12}
body{margin:0;background:var(--paper);color:var(--body);font:17px/1.6 "Newsreader",Georgia,serif}
.wrap{max-width:1000px;margin:0 auto;padding:40px 28px 100px}
h1,h2,h3{font-family:"Archivo",system-ui,sans-serif;color:var(--ink);letter-spacing:-.01em}
h1{font-size:2.4rem;line-height:1;margin:0 0 8px}h2{font-size:1.4rem;margin:44px 0 6px}
.kicker{font-family:"Archivo";font-size:12px;letter-spacing:.14em;text-transform:uppercase;
color:var(--accent);margin:0 0 12px}
.story{color:var(--ink);font-size:1.05rem;max-width:70ch;margin:0 0 8px}
.pre{font-family:"JetBrains Mono",monospace;font-size:.82rem;background:var(--surface);
padding:10px 14px;border-left:3px solid var(--rule);white-space:pre-wrap;margin:8px 0}
ol{padding-left:22px;max-width:72ch}li{margin:0 0 12px}
.do{color:var(--ink);font-weight:500}.see{display:block;color:var(--muted);font-size:.95rem}
.marks{font-family:"JetBrains Mono";font-size:.78rem;color:var(--muted)}
.out{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin:12px 0 0}
.card{border:1px solid var(--rule);background:var(--surface);padding:12px 14px;font-size:.93rem}
.card h4{font-family:"Archivo";margin:0 0 6px;font-size:.8rem;letter-spacing:.1em;
text-transform:uppercase;color:var(--muted)}
.PASS{color:var(--true)}.FAIL{color:var(--false)}.BLOCKED{color:var(--hold)}
.chip{font-family:"Archivo";font-weight:700;font-size:.85rem}
.shots{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin:10px 0}
.shots figure{margin:0}.shots img,.shots video{width:100%;border:1px solid var(--rule)}
.shots figcaption{font-family:"JetBrains Mono";font-size:11px;color:var(--muted);margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:.93rem;margin:12px 0}
th,td{text-align:left;padding:6px 10px 6px 0;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-family:"Archivo";font-size:11px;letter-spacing:.1em;text-transform:uppercase;
color:var(--muted)}
details{margin:6px 0}
summary{cursor:pointer;color:var(--accent);font-family:"Archivo";font-size:.9rem}
"""

FONTS = (
    "https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700"
    "&family=Newsreader:opsz,wght@6..72,400;6..72,500"
    "&family=JetBrains+Mono:wght@400;500&display=swap"
)


def _esc(x: object) -> str:
    return html.escape(str(x))


def _rel(path: str | None, out: Path) -> str | None:
    if not path:
        return None
    return os.path.relpath(path, out.parent)


def _story(j: dict) -> str:
    if j.get("goal"):
        return f"As a {j['persona']}, I want {j['goal']} because {j['because']}."
    return j["persona"]


def render(title: str, journeys: list[dict], runs: dict[str, list[dict]], out: Path) -> str:
    by_run = {name: {r["journey"]["id"]: r for r in results} for name, results in runs.items()}
    parts = [
        f'<!doctype html><html><head><meta charset="utf-8"><title>{_esc(title)}</title>',
        f'<link rel="stylesheet" href="{FONTS}"><style>{STYLE}</style></head>',
        '<body><div class="wrap">',
        '<p class="kicker">User journeys · authored from a diff · walked per build</p>',
        f"<h1>{_esc(title)}</h1>",
        "<h2>Summary</h2><table><tr><th>Journey</th>"
        + "".join(f"<th>{_esc(n)}</th>" for n in runs)
        + "</tr>",
    ]
    for j in journeys:
        cells = []
        for n in runs:
            r = by_run[n].get(j["id"])
            if not r:
                cells.append("<td>—</td>")
                continue
            failed_at = next((s["index"] + 1 for s in r["steps"] if s["outcome"] != "held"), None)
            where = f" at step {failed_at}" if failed_at and r["outcome"] != "pass" else ""
            cells.append(
                f'<td><span class="chip {r["outcome"].upper()}">{r["outcome"].upper()}</span>'
                f'{_esc(where)} <span class="marks">{_esc(r["why"][:110])}</span></td>'
            )
        parts.append(f"<tr><td>{_esc(j['id'])} · {_esc(j['title'])}</td>{''.join(cells)}</tr>")
    parts.append("</table>")
    for j in journeys:
        parts.append(f"<h2>{_esc(j['id'])} · {_esc(j['title'])}</h2>")
        parts.append(f'<p class="story">{_esc(_story(j))}</p>')
        pre = j.get("preconditions", {})
        lines = [f"{k}={v}" for k, v in pre.get("settings", {}).items()]
        lines += [f"state: {s}" for s in pre.get("state", [])]
        if lines:
            parts.append(f'<div class="pre">{_esc(chr(10).join(lines))}</div>')
        parts.append(f'<p class="marks">traces to: {_esc(j.get("traces_to", ""))}</p><ol>')
        for i, step in enumerate(j["steps"]):
            marks = []
            for n in runs:
                r = by_run[n].get(j["id"])
                if r:
                    marks.append(f"{n}: {MARK[r['steps'][i]['outcome']]}")
            parts.append(
                f'<li><span class="do">{_esc(step["do"])}</span> '
                f'<span class="marks">{_esc(" · ".join(marks))}</span>'
                f'<span class="see">see: {_esc(step["see"])}</span>'
            )
            shots = []
            for n in runs:
                r = by_run[n].get(j["id"])
                shot = _rel(r["steps"][i].get("screenshot") if r else None, out)
                if shot:
                    shots.append(
                        f'<figure><img src="{_esc(shot)}" alt="{_esc(n)} after step {i + 1}">'
                        f"<figcaption>{_esc(n)} · after step {i + 1}"
                        f" · {_esc(r['steps'][i]['reason'][:90])}</figcaption></figure>"
                    )
            if shots:
                parts.append(
                    f"<details><summary>screens after step {i + 1}</summary>"
                    f'<div class="shots">{"".join(shots)}</div></details>'
                )
            parts.append("</li>")
        parts.append("</ol>")
        cards = []
        for n in runs:
            r = by_run[n].get(j["id"])
            if not r:
                continue
            video = _rel(r.get("video"), out)
            vid = (
                f'<video controls preload="metadata" src="{_esc(video)}"></video>' if video else ""
            )
            cards.append(
                f'<div class="card"><h4>{_esc(n)}</h4>'
                f'<span class="chip {r["outcome"].upper()}">{r["outcome"].upper()}</span> '
                f"{_esc(r['why'])}{vid}</div>"
            )
        if cards:
            parts.append(f'<div class="out">{"".join(cards)}</div>')
    parts.append("</div></body></html>")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="journeys-viewer")
    p.add_argument("--title", required=True)
    p.add_argument("--journeys", help="journeys.json; defaults to the first run's")
    p.add_argument("--run", action="append", required=True, metavar="NAME=DIR")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    runs: dict[str, list[dict]] = {}
    for spec in args.run:
        name, d = spec.split("=", 1)
        runs[name] = json.loads((Path(d) / "results.json").read_text())
    first = Path(args.run[0].split("=", 1)[1])
    jpath = Path(args.journeys) if args.journeys else first / "journeys.json"
    journeys = json.loads(jpath.read_text())
    out = Path(args.out)
    out.write_text(render(args.title, journeys, runs, out))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
