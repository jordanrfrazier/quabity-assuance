# Local CLI Walkthrough

This walkthrough starts from a fresh plan instead of replaying a prepared local
artifact. Run commands from the qabot repository root and provide your own target
repository, refs, change description, and private dotenv file when credentials
are required.

## 1. Prepare Inputs

Prerequisites:
- macOS
- Google Chrome installed
- `git`, `uv`, `lsof`, and an authenticated `claude` CLI on `PATH`
- a local Git checkout of the application to test
- a base ref, head ref, and a short change description
- a private dotenv file only when the reviewed plan requires credential references

```sh
git clone https://github.com/jordanrfrazier/quabity-assuance.git qabot
cd qabot

export TARGET_REPO=/path/to/application-repo
export BASE_REF=main
export HEAD_REF=my-change
export CHANGE_DESCRIPTION=/path/to/change-description.md
export REVIEWER_NAME="Your name"
export PLAN_PATH=v1/reports/manual-first-use-01/plan.json
export RUN_DIR=v1/reports/manual-first-use-01/run-01

uv sync --extra dev --extra browser
uv run qabot journeys doctor --repo "$TARGET_REPO"
uv run qabot journeys --help
```

The change description is a user-created or existing file that explains what the
head ref is intended to change. If the approved plan later requires credentials,
set `PRIVATE_ENV_FILE` to a local dotenv file and pass it to `run`.

## 2. Generate A Draft Plan

```sh
uv run qabot journeys plan --repo "$TARGET_REPO" --base "$BASE_REF" --head "$HEAD_REF" \
  --description "$CHANGE_DESCRIPTION" --out "$PLAN_PATH"
```

Planning uses Claude/Sonnet through the local `claude` CLI and may send repository
diffs, documentation excerpts, and the change description to the model provider.
It does not execute setup commands, start the application, clone repositories, or
read a private dotenv file. Treat the JSON as a draft, not as a test result.

If the command reports unresolved items, resolve them in the plan or stop. Do not
approve a plan with startup commands, credentials, health checks, state, actions,
or expectations you cannot explain.

## 3. Review And Edit

Open `"$PLAN_PATH"` in your editor. Review:
- target repository identity and resolved base/head refs
- startup command, working directory, setup/reset commands, and cleanup behavior
- readiness URL and target port ownership assumptions
- required environment names and credential references
- required settings, including exact case and whitespace
- `preconditions.state`
- journey actions, expected observations, and whether each expected result follows
  from the change description

Credential values do not belong in the plan. Use complete `${NAME}` references.
At run time, `--env-file` loads only required names; explicit nonsecret plan values
still win. Login actions must name credential references. Recognized
credential-named startup environment entries and URLs with embedded credentials
are rejected before report creation unless they use full `${NAME}` references.

V1 fails closed on arbitrary prose state. Any nonempty `preconditions.state` list
blocks the journey before browser actions or model calls. A completed startup or
reset command alone does not prove that prose state. Preserve the requirement as
a verifiable fixture check or browser observation, or leave it blocked; do not
remove prerequisites only to obtain PASS.

## 4. Approve

```sh
uv run qabot journeys approve "$PLAN_PATH" --reviewer "$REVIEWER_NAME"
```

Approval creates an adjacent `.approval.json` file. Approval binds the reviewed
plan content, referenced executable script hashes, canonical target repository,
and resolved base/head commits. Changing execution-affecting content, moving a
branch, retargeting the repository, or changing a referenced script requires
renewed review. Formatting-only changes do not.

Historical example approvals are archived evidence. They should not be reused as
approval for your machine, target checkout, or edited plan.

## 5. Run

```sh
uv run qabot journeys run "$PLAN_PATH" --out "$RUN_DIR" --headed --channel chrome
```

If the approved plan requires credential references, use:

```sh
export PRIVATE_ENV_FILE=/path/to/private.env
uv run qabot journeys run "$PLAN_PATH" --out "$RUN_DIR" \
  --env-file "$PRIVATE_ENV_FILE" --headed --channel chrome
```

Use `--journey ID` to run selected journeys; repeat the flag for multiple IDs.
Omitting `--out` creates a unique directory under the primary Git workspace's
`v1/reports/`, or under the invocation directory outside Git. Supplying `--out`
must name a new run directory.

The runner starts and stops only the reviewed local application process. The port
must be free before setup and startup, and qabot refuses unrelated or detached
listeners because it cannot prove ownership. `lsof` is required for listener
ownership checks. The browser stays on the reviewed local origin; cross-origin SSO
is not supported in this pilot.

Each selected journey runs in a fresh browser context. Missing video, browser
cleanup failure, setup failure, unavailable credentials, model outage, or
unverifiable state can block a journey. Completed steps and findings remain in
the report even when cleanup or later evidence capture fails.

## 6. Inspect Evidence

Open the HTML report printed by the CLI:

```sh
open "$RUN_DIR/report.html"
```

Inspect `report.html`, `report.md`, `results.json`, startup logs, reset logs,
screenshots, and WebM videos. The report includes PASS/FAIL/BLOCKED outcomes,
configuration/state evidence, redacted command output, step evidence, approximate
video chapter links when timing exists, model call counts, and phase timing.
Step screenshots show the final observed state used for judgment; action records
retain their own per-action screenshots. If that final judged-state screenshot
cannot be captured, the step is BLOCKED with a capture diagnostic.

PASS means the reviewed observation was verified under the stated conditions. It
does not certify the whole application or unrun behavior. FAIL means observed
behavior contradicted the accepted expectation or an applicable failure rule.
BLOCKED means qabot could not establish the behavior.

The actor and judge receive page text and accessibility outlines, not screenshot
pixels. Spatial visibility, overlap, and visual styling still require human video
review. Text evidence is redacted for known credential values, but screenshots and
video are not pixel-redacted. Use disposable test data.

## 7. Rerun

An unchanged approved plan can be rerun to a fresh output directory:

```sh
uv run qabot journeys run "$PLAN_PATH" --out "${RUN_DIR}-rerun" --headed --channel chrome
```

Compare the new report with the prior run. Reruns capture fresh evidence; they do
not reuse old PASS/FAIL/BLOCKED results. If you edit actions, expected
observations, startup, reset, credentials, target repository, or refs, approve the
changed plan before running.

## 8. Bundle A Run

Package a completed run for local offline review:

```sh
uv run qabot journeys bundle "$RUN_DIR"
```

The command creates `"$RUN_DIR.zip"` beside the run and refuses to overwrite an
existing archive. It includes `report.html`, `report.md`, `results.json`, and
referenced screenshots/videos with relative links intact. It excludes standalone
logs, runtime configuration files, databases, credential files, and unreferenced
files. Missing evidence, malformed metadata, unsafe paths, absolute paths, and
symlink evidence fail clearly. Bundling does not rerun the app, rejudge outcomes,
call models, upload, host, or sanitize evidence.

Extract the ZIP before opening `report.html`. Review report metadata and media for
sensitive information before sharing.

## 9. Archived Evidence

Historical reports referenced in older notes remain archived local evidence, not
runnable prerequisites. Their paths may include prior machine-specific home,
temporary, or feature-worktree locations because they record where those validations ran.
Treat them as provenance for past decisions only. To evaluate a new target or a
different machine, generate and approve a new plan with the portable flow above.

The archived examples demonstrate useful limitations:
- model-generated journeys can need substantive human correction before approval
- provider errors are not successful application execution
- submitting a build is not proof that the build completed
- browser action success can still check the wrong expectation
- fresh browser contexts do not reset server-side data
- screenshots and videos may expose private page content
- missing or unverifiable initial state is BLOCKED, not PASS

This is a local pilot, not production-release certification.
