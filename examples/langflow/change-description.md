# Langflow Restricted-Mode Regression Review

Review these merged changes together on the fixed local revision.

## PR 14913

https://github.com/langflow-ai/langflow/pull/14913

Fix component lazy loading wiping the built-in registry. With
`LANGFLOW_LAZY_LOAD_COMPONENTS=true` and
`LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false`, loading must retain built-in components,
including Chat Input and Agent. Built-in category merges must preserve unrelated
components when custom paths contain a colliding category. Verify meaningful
user-visible flow creation and execution rather than only counting API entries.

## PR 14931

https://github.com/langflow-ai/langflow/pull/14931

Surface the restricted custom-component policy behind a substituted build failure.
An imported Agent flow can retain a custom input schema without the stock `model`
input. With `LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false`, the server substitutes its
stock Agent implementation. The build should be rejected, but the visible error
must explain that custom components are disabled, that the server's Agent replaced
the saved code, and how that substitution relates to the missing model input.
An expected rejection is a passing test only when this diagnostic is visible.

The environment is a local authenticated Langflow instance. Discover relevant
user-visible creation/build routes from repository source and documentation. Keep
required credentials as environment-variable references. Do not claim a successful
model build if a provider fails to authenticate or has no inference quota.
