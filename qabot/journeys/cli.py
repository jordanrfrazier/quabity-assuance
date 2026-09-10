"""Plan, review, approve, and execute local browser journeys."""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from qabot.journeys.approval import ApprovalError, approve_plan
from qabot.journeys.bundle import BundleError, bundle_run
from qabot.journeys.doctor import command as doctor_command
from qabot.journeys.llm import journey_provider
from qabot.journeys.runner import run_plan
from qabot.journeys.setup import DiscoveryError, discover_plan
from qabot.llm import LLMError


def default_run_directory(plan: Path) -> Path:
    root = Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root, capture_output=True, text=True, check=False, timeout=10,
        )
        if result.returncode == 0:
            common = Path(result.stdout.strip())
            if common.name == ".git":
                root = common.parent
    except FileNotFoundError:
        pass  # Outside a Git-capable environment, retain evidence in the invocation directory.
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return root / "v1" / "reports" / f"{stamp}-{plan.stem}-{uuid4().hex[:8]}"


def command(args):
    try:
        if args.journey_command == "plan":
            out = Path(args.out).resolve()
            if out.exists():
                raise ValueError(f"Plan already exists: {out}")
            description = Path(args.description).read_text() if args.description else ""
            plan = discover_plan(
                Path(args.repo), args.base, args.head, description, journey_provider(timeout=300)
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(plan.model_dump_json(indent=2) + "\n")
            print(
                f"Plan: {out}\nReview startup, configuration, and each expected observation before approval."
            )
            if plan.unresolved:
                print("Unresolved: " + "; ".join(plan.unresolved))
            return 0
        if args.journey_command == "approve":
            print(f"Approval: {approve_plan(Path(args.plan), args.reviewer)}")
            return 0
        if args.journey_command == "bundle":
            print(
                "Warning: journey metadata, screenshots, and video may contain sensitive "
                "information. Review the archive before sharing; qabot does not guarantee "
                "sanitization."
            )
            print(f"Bundle: {bundle_run(Path(args.run_dir))}")
            return 0
        if args.journey_command == "doctor":
            return doctor_command(args)
        out = Path(args.out).resolve() if args.out else default_run_directory(Path(args.plan))
        result = run_plan(
            Path(args.plan),
            out,
            headed=args.headed,
            channel=args.channel,
            selected=args.journey,
            env_file=Path(args.env_file) if args.env_file else None,
        )
        print(f"Report: {out / 'report.html'}")
        return result
    except (
        ApprovalError,
        BundleError,
        DiscoveryError,
        LLMError,
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"qabot journeys: {exc}", file=sys.stderr)
        return 2


def add_parser(sub):
    parser = sub.add_parser("journeys", help="reviewed local setup and recorded browser journeys")
    commands = parser.add_subparsers(dest="journey_command", required=True)
    plan = commands.add_parser("plan", help="discover startup and journeys without executing setup")
    plan.add_argument("--repo", required=True)
    plan.add_argument("--base", required=True)
    plan.add_argument("--head", required=True)
    plan.add_argument("--description", help="path to change description")
    plan.add_argument("--out", required=True)
    approve = commands.add_parser(
        "approve", help="record review of the current plan and local scripts"
    )
    approve.add_argument("plan")
    approve.add_argument("--reviewer", required=True)
    bundle = commands.add_parser(
        "bundle",
        help="create a local ZIP of reports and referenced journey evidence",
        description=(
            "Create a local ZIP beside RUN_DIR. The archive includes report.html, "
            "report.md, results.json, and only evidence files referenced by results.json. "
            "Review before sharing; no sanitization or upload is performed."
        ),
    )
    bundle.add_argument("run_dir", metavar="RUN_DIR")
    doctor = commands.add_parser(
        "doctor",
        help="check local journey prerequisites without auth or provider calls",
    )
    doctor.add_argument("--repo", help="optional local Git repository path to validate")
    run = commands.add_parser("run", help="start the approved application and record journeys")
    run.add_argument("plan")
    run.add_argument(
        "--out", help="new run directory; default: primary Git workspace v1/reports/<unique-run>"
    )
    run.add_argument("--headed", action="store_true")
    run.add_argument(
        "--env-file", help="local dotenv file; loads only the plan's required credential names"
    )
    run.add_argument("--channel", default="chrome", choices=["chrome", "chromium"])
    run.add_argument("--journey", action="append", help="run this journey ID; repeatable")
    parser.set_defaults(func=command)
