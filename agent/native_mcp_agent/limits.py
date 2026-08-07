"""Exact, conservative Phase 10.1 defaults and hard ceilings."""

from __future__ import annotations

from dataclasses import dataclass, fields

from .errors import FailureClass, ProviderError, failure


@dataclass(frozen=True)
class Limits:
    provider_request_bytes: int = 32 * 1024
    provider_response_bytes: int = 64 * 1024
    json_nesting_depth: int = 12
    object_array_items: int = 32
    message_count: int = 8
    message_bytes: int = 8 * 1024
    advertised_tool_count: int = 8
    tool_definition_bytes: int = 4 * 1024
    proposed_tool_call_count: int = 4
    tool_argument_bytes: int = 4 * 1024
    transcript_bytes: int = 32 * 1024
    provider_connect_timeout_ms: int = 500
    provider_read_inactivity_timeout_ms: int = 1_000
    provider_total_timeout_ms: int = 5_000
    provider_attempt_count: int = 3
    retry_backoff_ms: int = 50
    retry_after_ms: int = 1_000
    orchestration_total_timeout_ms: int = 15_000
    provider_turn_count: int = 4
    mcp_calls_per_turn: int = 4
    mcp_total_calls: int = 12
    mcp_request_bytes: int = 16 * 1024
    mcp_response_bytes: int = 64 * 1024
    child_stdout_bytes: int = 128 * 1024
    child_stderr_bytes: int = 64 * 1024
    process_startup_timeout_ms: int = 1_000
    mcp_initialize_timeout_ms: int = 1_000
    mcp_tools_list_timeout_ms: int = 1_000
    mcp_call_timeout_ms: int = 2_000
    graceful_shutdown_timeout_ms: int = 500

    HARD_MAX = {
        "provider_request_bytes": 256 * 1024,
        "provider_response_bytes": 512 * 1024,
        "json_nesting_depth": 24,
        "object_array_items": 128,
        "message_count": 32,
        "message_bytes": 32 * 1024,
        "advertised_tool_count": 32,
        "tool_definition_bytes": 16 * 1024,
        "proposed_tool_call_count": 16,
        "tool_argument_bytes": 16 * 1024,
        "transcript_bytes": 128 * 1024,
        "provider_connect_timeout_ms": 5_000,
        "provider_read_inactivity_timeout_ms": 10_000,
        "provider_total_timeout_ms": 30_000,
        "provider_attempt_count": 5,
        "retry_backoff_ms": 500,
        "retry_after_ms": 5_000,
        "orchestration_total_timeout_ms": 120_000,
        "provider_turn_count": 16,
        "mcp_calls_per_turn": 16,
        "mcp_total_calls": 64,
        "mcp_request_bytes": 128 * 1024,
        "mcp_response_bytes": 512 * 1024,
        "child_stdout_bytes": 1024 * 1024,
        "child_stderr_bytes": 512 * 1024,
        "process_startup_timeout_ms": 10_000,
        "mcp_initialize_timeout_ms": 10_000,
        "mcp_tools_list_timeout_ms": 10_000,
        "mcp_call_timeout_ms": 30_000,
        "graceful_shutdown_timeout_ms": 5_000,
    }

    def __post_init__(self) -> None:
        for item in fields(self):
            name = item.name
            value = getattr(self, name)
            maximum = self.HARD_MAX[name]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > maximum:
                raise ProviderError(
                    failure(
                        FailureClass.INVALID_PROVIDER_CONFIGURATION,
                        f"limit {name} is outside its bounded range",
                    )
                )

    def as_dict(self) -> dict[str, int]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


DEFAULT_LIMITS = Limits()
HARD_LIMITS = Limits(**Limits.HARD_MAX)
