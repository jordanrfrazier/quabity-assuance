"""CLI tests, focused on the credentials `qabot run` accepts and what becomes of them.

Two claims are worth a test each. The first is that the flags reach the driver at
all: a `--header` that parses into nothing produces a run of 401s that reads as a
broken application, and nothing in the report would say otherwise.

The second is the one that matters more. A report is pasted into a pull request and
a generated test is committed to a repository, so a token that survives into either
is a token the customer now has to rotate. The last test here runs the real CLI
against a real server with a real `--header` and looks for that token in every
artifact the run produces -- rendered report, serialized report, emitted test file.
It greps for the literal string rather than asserting on structure on purpose: the
point is not that we redacted the fields we thought of.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from demo.app import create_app
from demo.server import serve
from qabot import cli
from qabot.drivers.http import REDACTED, HttpDriver
from qabot.models import (
    Anchor,
    AnchorKind,
    Criticality,
    Expectation,
    KnowledgeBase,
    Provenance,
    Step,
    Workflow,
)
from qabot.store import KBStore

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Distinctive enough that a leak test greping for them cannot pass by coincidence.
TOKEN = "sk-live-4b71ee-not-a-real-token"
BEARER = f"Bearer {TOKEN}"
SESSION = "sess-9d20-not-a-real-session"

#: A diff over the demo app, so the file anchor below is implicated and the workflow
#: is actually selected. Content of the context line is irrelevant to the parser;
#: only the file header and the line count are.
DIFF = (
    "diff --git a/demo/app.py b/demo/app.py\n"
    "--- a/demo/app.py\n"
    "+++ b/demo/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    ' """Demo app."""\n'
    "+# (pretend this PR touched the cart)\n"
)


def knowledge_base() -> KnowledgeBase:
    """One workflow that passes cleanly against the demo app, so the run produces all
    three artifacts: a report, a serialized report, and an emitted regression test."""
    return KnowledgeBase(
        repo="demo/shop",
        workflows=[
            Workflow(
                id="wf_cart",
                name="Add a widget to the cart",
                criticality=Criticality.HIGH,
                steps=[
                    Step(
                        intent="add a widget to the cart",
                        hint={
                            "method": "POST",
                            "path": "/cart/items",
                            "json": {"sku": "widget", "qty": 1},
                        },
                    )
                ],
                expectations=[
                    Expectation(
                        id="e_created",
                        statement="adding an item creates the cart",
                        provenance=Provenance.HUMAN_CONFIRMED,
                        check={"kind": "status", "value": 201},
                        step_index=0,
                    )
                ],
                anchors=[Anchor(kind=AnchorKind.FILE, locator="demo/app.py")],
            )
        ],
    )


def run_argv(tmp_path: Path, *extra: str) -> list[str]:
    kb_path = tmp_path / "kb.json"
    KBStore(kb_path).save(knowledge_base())
    diff_path = tmp_path / "change.diff"
    diff_path.write_text(DIFF)
    return [
        "run",
        "--kb",
        str(kb_path),
        "--base-url",
        "http://127.0.0.1:1",
        "--source-root",
        str(REPO_ROOT),
        "--diff",
        str(diff_path),
        *extra,
    ]


def test_header_arg_parses_name_and_value() -> None:
    assert cli._header_arg("Authorization: Bearer abc") == ("Authorization", "Bearer abc")


def test_cookie_arg_parses_name_and_value() -> None:
    assert cli._cookie_arg("session=abc123") == ("session", "abc123")


@pytest.mark.parametrize("raw", ["Authorization Bearer abc", ": abc", "Authorization:  "])
def test_a_malformed_header_is_rejected(raw: str) -> None:
    """Rejected, never dropped. A credential we silently ignored is a run that reports
    an application as broken when the only thing broken was the invocation."""
    with pytest.raises(cli.argparse.ArgumentTypeError):
        cli._header_arg(raw)


@pytest.mark.parametrize("raw", ["sessionabc", "=abc", "session="])
def test_a_malformed_cookie_is_rejected(raw: str) -> None:
    with pytest.raises(cli.argparse.ArgumentTypeError):
        cli._cookie_arg(raw)


def test_a_rejected_credential_is_not_echoed(tmp_path: Path, capsys) -> None:
    """argparse's error lands in a CI log. A malformed credential is still a
    credential, so the message describes the shape and prints none of the value."""
    with pytest.raises(SystemExit):
        cli.main(run_argv(tmp_path, "--header", f"Authorization {BEARER}"))

    stderr = capsys.readouterr().err
    assert "expected 'Name: Value'" in stderr
    assert TOKEN not in stderr


def test_run_hands_the_parsed_credentials_to_the_driver(tmp_path: Path, monkeypatch) -> None:
    """The flags exist to reach the driver. A parser that parses into nothing is the
    failure this rules out, and it is invisible from the report."""
    captured: dict[str, object] = {}
    client = TestClient(create_app(), base_url="http://test")

    def recorder(**kwargs: object) -> HttpDriver:
        captured.update(kwargs)
        return HttpDriver(
            base_url="http://test",
            client=client,
            headers=kwargs["headers"],  # type: ignore[arg-type]
            cookies=kwargs["cookies"],  # type: ignore[arg-type]
        )

    monkeypatch.setattr(cli, "HttpDriver", recorder)
    code = cli.main(
        run_argv(tmp_path, "--header", f"Authorization: {BEARER}", "--cookie", f"session={SESSION}")
    )
    client.close()

    assert code == 0
    assert captured["headers"] == {"Authorization": BEARER}
    assert captured["cookies"] == {"session": SESSION}


def test_a_token_passed_via_header_reaches_no_artifact(tmp_path: Path, monkeypatch, capsys) -> None:
    """The whole point, end to end: real CLI, real server, real --header.

    Every artifact of the run is searched for the literal token -- what a human reads,
    what a machine consumes, and what gets committed to a repository. The report is
    caught by spying on the runner because `qabot run` prints it rather than returning
    it, and a leak in the serialized form would outlive the rendered one.
    """
    reports = []
    real_run = cli.run_qa

    def spy(**kwargs: object):
        report = real_run(**kwargs)  # type: ignore[arg-type]
        reports.append(report)
        return report

    monkeypatch.setattr(cli, "run_qa", spy)
    out_dir = tmp_path / "generated"

    with serve(create_app()) as base_url:
        argv = run_argv(
            tmp_path,
            "--emit-tests",
            str(out_dir),
            "--header",
            f"Authorization: {BEARER}",
            "--cookie",
            f"session={SESSION}",
        )
        argv[argv.index("--base-url") + 1] = base_url
        code = cli.main(argv)

    assert code == 0
    rendered = capsys.readouterr().out
    serialized = reports[0].model_dump_json()
    generated = (out_dir / "test_qa_generated.py").read_text()

    for artifact in (rendered, serialized, generated):
        assert TOKEN not in artifact
        assert SESSION not in artifact

    # Redaction, not deletion: the evidence still says an Authorization header was
    # sent, because a reader debugging a 403 needs to know whether we authenticated.
    assert f'"Authorization":"{REDACTED}"' in serialized
    assert f'"session":"{REDACTED}"' in serialized
    # And the generated test says out loud that it replays without those credentials,
    # rather than shipping a file that fails for reasons nothing in it explains.
    assert "The generating run authenticated" in generated
