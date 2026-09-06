"""Author journeys from a change, then walk them against a running instance.

    uv run python -m spikes.journeys.run --repo PATH --base REF --head REF \\
        --url http://127.0.0.1:7860 --out runs/journeys/fixed [--pr-text FILE] \\
        [--author-only] [--journeys FILE] [--headed]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from qabot.llm import LLMError
from spikes.journeys.author import author
from spikes.journeys.evidence import DIFF_CAP, gather
from spikes.journeys.launcher import Instance, LaunchSpec, group_by_settings, resolve_settings
from spikes.journeys.models import Journey
from spikes.journeys.report import render
from spikes.journeys.snapshot import SNAPSHOT_CAP
from spikes.journeys.walker import MAX_ACTIONS_PER_STEP, walk


def _llm():
    spec = os.environ.get("JOURNEYS_LLM", "")
    if spec.startswith("fake:"):
        from spikes.journeys.fakes import FakeLLM

        return FakeLLM(json.loads(Path(spec[5:]).read_text()))
    from qabot.llm import ClaudeCliLLM

    return ClaudeCliLLM(timeout=180.0)


def _new_context(browser, out: Path, journey: Journey, video: bool):
    """A fresh context per journey, recording it when asked. The recording is the
    evidence a reader can replay: every click, in order, at the speed it happened."""
    kwargs: dict = {"viewport": {"width": 1440, "height": 900}}
    if video:
        kwargs["record_video_dir"] = str(out / "video" / journey.id)
        kwargs["record_video_size"] = {"width": 1440, "height": 900}
    return browser.new_context(**kwargs)


def _finish_context(context, page, out: Path, journey: Journey, video: bool) -> str | None:
    """Close the context; the video file only exists once it is closed."""
    recording = page.video if video else None
    context.close()
    if recording is None:
        return None
    try:
        src = Path(recording.path())
        dst = out / "video" / f"{journey.id}.webm"
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        return str(dst)
    except Exception:  # noqa: BLE001 -- a lost recording is reported as absent, not fatal
        return None


def _blocked(journey: Journey, why: str):
    from qabot.models import Outcome
    from spikes.journeys.models import JourneyResult, StepOutcome, StepResult

    return JourneyResult(
        journey=journey,
        outcome=Outcome.BLOCKED,
        steps=[
            StepResult(index=i, do=st.do, see=st.see, outcome=StepOutcome.NOT_REACHED, reason=why)
            for i, st in enumerate(journey.steps)
        ],
        why=why,
    )


def _walk_one(journey: Journey, driver, page, llm, shots: Path, env, context, out, video):
    """Walk one journey; a model outage becomes a BLOCKED result, never a crash, and the
    recording is attached whichever way the walk ended."""
    from qabot.llm import LLMError
    from qabot.models import Outcome
    from spikes.journeys.models import JourneyResult, StepOutcome, StepResult

    try:
        result = walk(journey, driver, page, llm, shots, env)
    except LLMError as exc:
        why = f"the model was unavailable: {exc}"
        result = JourneyResult(
            journey=journey,
            outcome=Outcome.BLOCKED,
            steps=[
                StepResult(
                    index=i, do=st.do, see=st.see, outcome=StepOutcome.NOT_REACHED, reason=why
                )
                for i, st in enumerate(journey.steps)
            ],
            why=why,
        )
    finally:
        recording = _finish_context(context, page, out, journey, video)
    result.video = recording
    return result


def _walk_all(
    journeys: list[Journey],
    url: str,
    out: Path,
    llm,
    headed: bool,
    env: dict[str, str] | None,
    video: bool = False,
) -> list:
    from playwright.sync_api import sync_playwright

    from qabot.drivers.browser import BrowserDriver

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        for journey in journeys:
            context = _new_context(browser, out, journey, video)
            page = context.new_page()
            shots = out / "shots" / journey.id
            driver = BrowserDriver(
                base_url=url, page=page, artifacts_dir=shots, timeout_ms=15000.0, reset_path=None
            )
            results.append(_walk_one(journey, driver, page, llm, shots, env, context, out, video))
            print(f"{journey.id} {results[-1].outcome.value}: {journey.title}", file=sys.stderr)
        browser.close()
    return results


def _walk_launching(
    journeys: list[Journey], spec: LaunchSpec, out: Path, llm, headed: bool, video: bool = False
) -> tuple[list, list[dict]]:
    """Start the application once per distinct settings group, walk that group, stop.

    Every journey is walked under the settings it declared, so the precondition gate
    passes by construction and a BLOCKED can only mean the walk itself could not proceed.
    What was written to disk to satisfy a described precondition is returned for the report.
    """
    from playwright.sync_api import sync_playwright

    from qabot.drivers.browser import BrowserDriver

    results: list = []
    environments: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        for n, (settings, members) in enumerate(group_by_settings(journeys), start=1):
            try:
                env, made = resolve_settings(settings, out / "fixtures" / f"group_{n}", llm)
            except LLMError as exc:
                why = f"the model was unavailable while preparing this group's fixtures: {exc}"
                environments.append(
                    {
                        "group": n,
                        "journeys": [j.id for j in members],
                        "env": {},
                        "materialised": [],
                        "error": why,
                    }
                )
                results.extend(_blocked(j, why) for j in members)
                print(f"group {n}: skipped; {why}", file=sys.stderr)
                continue
            record = {
                "group": n,
                "journeys": [j.id for j in members],
                "env": env,
                "materialised": [m.model_dump() for m in made],
            }
            environments.append(record)
            instance = Instance(spec, env, out / "logs" / f"group_{n}.log")
            print(f"group {n}: starting with {env}", file=sys.stderr)
            instance.start()
            healthy = instance.wait_healthy()
            try:
                if not healthy:
                    record["error"] = "application did not become healthy"
                    print(f"group {n}: not healthy; see {instance.log_path}", file=sys.stderr)
                for journey in members:
                    if not healthy:
                        from qabot.models import Outcome
                        from spikes.journeys.models import JourneyResult, StepOutcome, StepResult

                        why = "the application did not start with this journey's settings"
                        results.append(
                            JourneyResult(
                                journey=journey,
                                outcome=Outcome.BLOCKED,
                                steps=[
                                    StepResult(
                                        index=i,
                                        do=st.do,
                                        see=st.see,
                                        outcome=StepOutcome.NOT_REACHED,
                                        reason=why,
                                    )
                                    for i, st in enumerate(journey.steps)
                                ],
                                why=why,
                            )
                        )
                        continue
                    context = _new_context(browser, out, journey, video)
                    page = context.new_page()
                    shots = out / "shots" / journey.id
                    base_url = spec.health_url.rsplit("/", 1)[0]
                    driver = BrowserDriver(
                        base_url=base_url,
                        page=page,
                        artifacts_dir=shots,
                        timeout_ms=15000.0,
                        reset_path=None,
                    )
                    results.append(
                        _walk_one(journey, driver, page, llm, shots, env, context, out, video)
                    )
                    print(
                        f"{journey.id} {results[-1].outcome.value}: {journey.title}",
                        file=sys.stderr,
                    )
            finally:
                instance.stop()
        browser.close()
    return results, environments


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="journeys")
    p.add_argument("--repo", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--url")
    p.add_argument("--pr-text")
    p.add_argument("--journeys", help="reuse authored journeys from this file")
    p.add_argument("--author-only", action="store_true")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--video", action="store_true", help="record each journey's browser to a video")
    p.add_argument("--launch", help="command that starts the app; run once per settings group")
    p.add_argument("--health", help="URL that answers 2xx when the app is up (launch mode)")
    p.add_argument("--cwd", help="working directory for --launch")
    p.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="a setting the instance was started with; journeys needing others are blocked",
    )
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    llm = _llm()

    description = Path(args.pr_text).read_text() if args.pr_text else ""
    evidence = gather(Path(args.repo), args.base, args.head, description)
    (out / "evidence.json").write_text(evidence.model_dump_json(indent=1))
    if args.journeys:
        loaded = json.loads(Path(args.journeys).read_text())
        journeys = [Journey.model_validate(j) for j in loaded]
    else:
        journeys = author(evidence, llm)
    (out / "journeys.json").write_text(
        json.dumps([j.model_dump() for j in journeys], indent=1, ensure_ascii=False)
    )
    print(f"{len(journeys)} journeys -> {out / 'journeys.json'}", file=sys.stderr)
    if args.author_only:
        return 0
    environments: list[dict] = []
    if args.launch:
        if not (args.health and args.cwd):
            print("--launch needs --health and --cwd", file=sys.stderr)
            return 2
        base_env = dict(kv.split("=", 1) for kv in args.env) if args.env else {}
        spec = LaunchSpec(
            command=args.launch, health_url=args.health, cwd=args.cwd, base_env=base_env
        )
        results, environments = _walk_launching(journeys, spec, out, llm, args.headed, args.video)
    elif args.url:
        env = dict(kv.split("=", 1) for kv in args.env) if args.env else None
        results = _walk_all(journeys, args.url, out, llm, args.headed, env, args.video)
    else:
        print("--url or --launch is required to walk journeys", file=sys.stderr)
        return 2
    (out / "environments.json").write_text(json.dumps(environments, indent=1))
    caps = {
        "snapshot_chars": SNAPSHOT_CAP,
        "diff_chars": DIFF_CAP,
        "actions_per_step": MAX_ACTIONS_PER_STEP,
    }
    (out / "results.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in results], indent=1, ensure_ascii=False)
    )
    (out / "report.md").write_text(render(results, evidence, caps))
    print(f"report -> {out / 'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
