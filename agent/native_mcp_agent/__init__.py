"""Provider-neutral, bounded Phase 10.1 contracts.

This package deliberately contains no MCP client, provider SDK, credential
loader, or live-provider implementation.
"""

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
]
