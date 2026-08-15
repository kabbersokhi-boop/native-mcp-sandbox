# Phase 10.4: optional OpenAI-compatible adapter

Phase 10.4 adds a bounded non-streaming provider adapter to the external
Python agent.  The C++ `native-mcp-sandbox` remains stdio-only, network-free,
credential-free, and exposes no new tools.

## Configuration and credentials

`OpenAICompatibleConfig.from_mapping()` accepts only `endpoint`, `model`,
`credentialEnv`, `verifyTls`, `allowLoopbackHttp`, `dataFlow`, and the closed
`limits` object.  Model and endpoint are operator-configurable; no provider,
endpoint, or model is hard-coded. `credentialEnv` must be a narrowly named
`NATIVE_MCP_*` environment variable. Its value is read only at explicit
**production verified-HTTPS** execution, never on import or adapter
construction, and is sent only as the bounded provider request's HTTP
Authorization header. The deterministic loopback HTTP path cannot read that
environment variable and has no credential-bearing transport API or
Authorization header.

Timeouts, attempt count, retry backoff, Retry-After bound, request byte limit,
and response byte limit are the existing bounded `Limits` fields. Unknown
configuration fields and unknown limit names fail closed.

## Network and response policy

Production endpoints require verified HTTPS, reject user-info, query/fragment
forms, redirects, and TLS-verification disablement. The existing endpoint
policy is reused and production DNS resolution immediately before connection
rejects non-global addresses. The loopback HTTP exception is test-only,
requires explicit configuration, is loopback-only, and is credential-free.
HTTP is bounded and non-streaming: requests are sized before send, responses
are bounded as read, redirects are not followed, content type is checked, and
errors use the project failure taxonomy/retry policy.

The adapter maps only the neutral request fields to a closed
OpenAI-compatible `chat/completions` request with `stream: false`. It maps a
closed `choices` response envelope to either one assistant message or ordered
tool proposals. Tool definitions come solely from the captured MCP surface;
tool calls then pass the existing advertised-tool allowlist, argument schema,
authorization, action identity, serial execution, and replay protections.
Provider text remains guidance, never evidence.

## Offline CI and optional smoke

All automated tests use the deterministic loopback fake provider and
synthetic-only prompts/data. Normal CI has no credential or external-network
requirement. `synthetic-only` is the only accepted data-flow mode: every
initial outbound message must be minted from the adapter's closed, committed
`SyntheticFixture` set under immutable project-issued authorization. There is
no public plain-string authorization factory; matching text alone is never
sufficient. Authorization is held in a private non-transferable issuance
record bound to committed role/content literals, so copied messages or
post-issuance fixture/message mutations invalidate authorization. Later tool
evidence cannot silently leave the agent.

An operator may run the non-gating manual smoke with explicit endpoint, model,
credential variable name, and `--enable-synthetic-live`:

```sh
python3 scripts/phase_10_4_openai_smoke.py --enable-synthetic-live \
  --endpoint https://provider.example/v1/chat/completions \
  --model operator-selected-model --credential-env NATIVE_MCP_PROVIDER_TOKEN
```

It uses only a synthetic prompt, prints bounded/redacted status rather than
provider text, and is observational only—not CI or merge evidence. Streaming,
parallel MCP execution, C++ networking/credentials, new native MCP tools, and
release/tag work remain explicit non-goals.
