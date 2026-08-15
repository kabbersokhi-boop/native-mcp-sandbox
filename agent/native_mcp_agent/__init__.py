"""Provider-neutral bounded orchestration contracts (no live provider SDK)."""

from .contracts import (
    AdvertisedTool,
    EvidenceProvenance,
    GenerationControls,
    LocalActionIdentity,
    ModelIdentifier,
    ProviderConfig,
    ProviderFinalMessage,
    ProviderMessage,
    ProviderRequest,
    ProviderToolCallProposal,
    RequestCorrelationId,
    new_request_correlation_id,
    RetryDecision,
    ToolCallId,
    parse_provider_response,
)
from .errors import ClassifiedFailure, FailureClass, ProviderError
from .limits import DEFAULT_LIMITS, Limits
from .mcp_orchestrator import BoundedProvider, CancellationToken, McpStdioClient, Orchestrator, OrchestrationOutcome, ScriptedProvider
from .openai_compatible import AuthorizedSyntheticMessage, OpenAICompatibleConfig, OpenAICompatibleProvider, OpenAICompatibleTransport, authorized_synthetic_message, openai_request_bytes, parse_openai_compatible_response

__all__ = [
    "AdvertisedTool",
    "ClassifiedFailure",
    "DEFAULT_LIMITS",
    "EvidenceProvenance",
    "FailureClass",
    "GenerationControls",
    "Limits",
    "LocalActionIdentity",
    "ModelIdentifier",
    "ProviderConfig",
    "ProviderError",
    "ProviderFinalMessage",
    "ProviderMessage",
    "ProviderRequest",
    "ProviderToolCallProposal",
    "RequestCorrelationId",
    "new_request_correlation_id",
    "RetryDecision",
    "ToolCallId",
    "parse_provider_response",
    "McpStdioClient",
    "CancellationToken",
    "Orchestrator",
    "OrchestrationOutcome",
    "ScriptedProvider",
    "BoundedProvider",
    "OpenAICompatibleConfig",
    "OpenAICompatibleProvider",
    "OpenAICompatibleTransport",
    "AuthorizedSyntheticMessage",
    "authorized_synthetic_message",
    "openai_request_bytes",
    "parse_openai_compatible_response",
]
