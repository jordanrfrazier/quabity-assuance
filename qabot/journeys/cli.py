"""Plan, review, approve, and execute local browser journeys."""

import sys
from pathlib import Path

from qabot.journeys.approval import ApprovalError, approve_plan
from qabot.journeys.llm import journey_provider
from qabot.journeys.runner import run_plan
from qabot.journeys.setup import DiscoveryError, discover_plan
from qabot.llm import LLMError


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
        result = run_plan(
            Path(args.plan),
            Path(args.out),
            headed=args.headed,
            channel=args.channel,
            selected=args.journey,
            env_file=Path(args.env_file) if args.env_file else None,
        )
        print(f"Report: {Path(args.out).resolve() / 'report.html'}")
        return result
    except (ApprovalError, DiscoveryError, LLMError, OSError, ValueError) as exc:
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
    run = commands.add_parser("run", help="start the approved application and record journeys")
    run.add_argument("plan")
    run.add_argument("--out", required=True, help="new, non-existing run directory")
    run.add_argument("--headed", action="store_true")
    run.add_argument(
        "--env-file", help="local dotenv file; loads only the plan's required credential names"
    )
    run.add_argument("--channel", default="chrome", choices=["chrome", "chromium"])
    run.add_argument("--journey", action="append", help="run this journey ID; repeatable")
    parser.set_defaults(func=command)
