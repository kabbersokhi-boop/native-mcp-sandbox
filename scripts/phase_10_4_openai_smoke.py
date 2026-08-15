#!/usr/bin/env python3
"""Opt-in synthetic observational smoke for an OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.native_mcp_agent.contracts import ProviderRequest, RequestCorrelationId
from agent.native_mcp_agent.errors import ProviderError
from agent.native_mcp_agent.openai_compatible import (
    OpenAICompatibleConfig, OpenAICompatibleProvider, SyntheticFixture, synthetic_fixture_message,
)


def build_synthetic_smoke_request(config: OpenAICompatibleConfig) -> ProviderRequest:
    """Build the smoke prompt through the adapter's project-owned egress path."""
    return ProviderRequest(
        config.model,
        (synthetic_fixture_message(SyntheticFixture.PHASE_10_4_MANUAL_SMOKE_PROMPT),),
        (),
        32,
        RequestCorrelationId("req-10-4-1"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual Phase 10.4 synthetic provider smoke (non-gating).")
    parser.add_argument("--enable-synthetic-live", action="store_true", help="required explicit opt-in")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--credential-env", required=True)
    args = parser.parse_args()
    if not args.enable_synthetic_live:
        parser.error("--enable-synthetic-live is required; this smoke is disabled by default")
    try:
        config = OpenAICompatibleConfig(endpoint=args.endpoint, model=args.model, credential_env=args.credential_env)
        request = build_synthetic_smoke_request(config)
        result = OpenAICompatibleProvider(config).turn(request, (), timeout_ms=config.limits.provider_total_timeout_ms, cancellation=None)
        # Do not print the arbitrary provider text; this is observational only.
        print("synthetic provider smoke: response accepted (observational only; not CI or merge evidence)")
        del result
        return 0
    except ProviderError as error:
        print("synthetic provider smoke: " + error.failure.safe_text(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
