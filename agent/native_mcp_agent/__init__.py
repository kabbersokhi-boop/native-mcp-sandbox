"""Provider-neutral, bounded Phase 10.1 contracts.

This package deliberately contains no MCP client, provider SDK, credential
loader, or live-provider implementation.
"""

from .contracts import (
    AdvertisedTool,
    EvidenceProvenance,
    GenerationControls,
    LocalActionIdentity,
    ProviderConfig,
    ProviderFinalMessage,
    ProviderMessage,
    ProviderRequest,
    ProviderToolCallProposal,
    RequestCorrelationId,
    RetryDecision,
    ToolCallId,
    parse_provider_response,
)
from .errors import ClassifiedFailure, FailureClass, ProviderError
from .limits import DEFAULT_LIMITS, Limits

__all__ = [
    "AdvertisedTool",
    "ClassifiedFailure",
    "DEFAULT_LIMITS",
    "EvidenceProvenance",
    "FailureClass",
    "GenerationControls",
    "Limits",
    "LocalActionIdentity",
    "ProviderConfig",
    "ProviderError",
    "ProviderFinalMessage",
    "ProviderMessage",
    "ProviderRequest",
    "ProviderToolCallProposal",
    "RequestCorrelationId",
    "RetryDecision",
    "ToolCallId",
    "parse_provider_response",
]
