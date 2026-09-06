# Agent Review Notes

Reviewer status: agent-reviewed for local automated validation; not human-confirmed.

The untouched real-model output is `generated-plan.json`. It was not approved because
its evidence was contaminated by an unrelated historical design diff and it described
a different application. Unsupported claims included:

- `uv run python -m shop`, `/healthz`, `PAYMENT_API_KEY`, `SHOP_CATALOG`, and a gateway
  stub that do not exist in the bundled demo;
- nonexistent `demo/shop`, template, and catalog files;
- dollar-denominated products, `/cart`, and `/checkout` pages that do not match `/ui`;
- seven journeys, including direct JSON POST behavior the browser walker cannot perform;
- a no-op reset and shared global cart, contradicting the actual `ShopState.clear()`
  implementation and per-app state.

The reviewed plan uses the actual uvicorn application, `/health`, `/reset`, and `/ui`
controls. It contains only the requested widget, valid checkout, and expired-card paths.
The expired-card rejection is explicitly expected, while its generic message and cleared
cart remain observations that should fail against repository-authored expectations.

Run 1 preserved videos for all three journeys but blocked before completing any journey.
The walker tried `/` and `/shop` because the reviewed action said only "Open the shop UI".
The third journey eventually found `/ui` and reached the correct populated cart, but used
all six decisions doing so. The plan was revised to name the actual `/ui` entry point from
`ui.py`; no expected observation was weakened.

Run 2 passed the widget and valid-card journeys. In the expired-card journey, the first
submission reached the expected rejection state, visibly showing `Payment failed`, an
empty cart, and zero total. Because the Place order control remained present, the walker
submitted the same expired payment three times and exhausted the action budget instead
of judging the contradiction. The action was revised to specify one submission and no
resubmission. The expected expired-card message and retained widget remain unchanged.

Run 3 then exposed a provider protocol failure: after reaching a populated cart, Claude
returned bare `done` rather than JSON. Run 4, after the first structured-output change,
returned the intended action JSON nested inside the `op` string. Both runs were kept as
blocked evidence and no application behavior was inferred from those provider failures.

Run 5 used the strict operation schema and the same renewed approval. It submitted the
expired checkout once, then reported FAIL: the alert only said `Payment failed`, and the
cart showed empty with a zero-cent total. The inferred mismatch remained severity
`question`; the expected rejection was not mislabeled as an intrinsic application BUG.

Post-fix discovery output is preserved as `generated-plan-v2.json`. It no longer invents
the other shop package or credentials and proposes exactly three relevant journeys, but
it still omits `ui.py` evidence. As a result, it leaves the startup command unresolved and
describes browser actions as "locate and use the mechanism" rather than naming `/ui` and
its accessible controls. It was not approved.
