"""synthetix_alpha.pipeline — LLM-driven daily trade pipeline.

Screen → Gather → Critique → Risk Gate → Execute.
"""

from synthetix_alpha.pipeline.critic import CriticAgent, CriticDecision, CriticInput
from synthetix_alpha.pipeline.llm import LLMAPIError, LLMClient
from synthetix_alpha.pipeline.orchestrator import (
    PipelineOrchestrator,
    PipelineResult,
    main,
)

__all__ = [
    "CriticAgent", "CriticDecision", "CriticInput",
    "LLMAPIError", "LLMClient",
    "PipelineOrchestrator", "PipelineResult", "main",
]