"""The qualification pipeline: signals, then wedges, then MEDDPICC, then the brief.

Pure functions over the models. Signals are collected beforehand (scrapers or the mock
layer) and the LLM is injected, so the same pipeline runs offline and live.
"""

from datetime import datetime

from anthropic_prospector.models import LLMUsage, SDROutboundBrief, StartupProfile
from anthropic_prospector.pipeline.brief_builder import build_brief, to_markdown
from anthropic_prospector.pipeline.displacement_matrix import build_value_props
from anthropic_prospector.pipeline.llm import (
    AnthropicLLMClient,
    LLMClient,
    LLMError,
    MockLLMClient,
)
from anthropic_prospector.pipeline.meddpicc_generator import baseline_scorecard, refine_scorecard

__all__ = [
    "AnthropicLLMClient",
    "LLMClient",
    "LLMError",
    "MockLLMClient",
    "run_pipeline",
    "to_markdown",
]


def run_pipeline(
    profile: StartupProfile, llm: LLMClient, *, generated_at: datetime | None = None
) -> tuple[SDROutboundBrief, LLMUsage]:
    """Qualify one account whose signals are already collected (profile.tech_stack is set)."""
    value_props = build_value_props(profile)
    baseline = baseline_scorecard(profile, value_props)
    scorecard, refine_usage = refine_scorecard(baseline, profile, value_props, llm)
    brief, brief_usage = build_brief(
        profile, value_props, scorecard, llm, generated_at=generated_at
    )
    return brief, refine_usage + brief_usage
