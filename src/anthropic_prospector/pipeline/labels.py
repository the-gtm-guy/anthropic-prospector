"""Display names shared by the pipeline modules (which may not import each other)."""

from typing import Final

from anthropic_prospector.models import (
    CloudProvider,
    CompetitorKind,
    FundingStage,
    MEDDPICCElement,
    Persona,
    WedgeId,
)

MARKETPLACES: Final = {
    CloudProvider.AWS: "Amazon Bedrock",
    CloudProvider.GCP: "Google Cloud Vertex AI",
    CloudProvider.AZURE: "Microsoft Foundry",
}
CLOUD_NAMES: Final = {
    CloudProvider.AWS: "AWS",
    CloudProvider.GCP: "Google Cloud",
    CloudProvider.AZURE: "Azure",
}
COMPETITOR_NAMES: Final = {
    CompetitorKind.OPENAI: "the OpenAI API",
    CompetitorKind.AZURE_OPENAI: "Azure OpenAI",
    CompetitorKind.LANGCHAIN: "LangChain",
    CompetitorKind.VLLM: "self-hosted models on vLLM",
    CompetitorKind.OTHER_LLM: "another model provider",
    CompetitorKind.ANTHROPIC_EXISTING: "Claude",
}
STAGE_LABELS: Final = {
    FundingStage.PRE_SEED: "pre-seed",
    FundingStage.SEED: "seed",
    FundingStage.SERIES_A: "Series A",
    FundingStage.SERIES_B: "Series B",
    FundingStage.SERIES_C_PLUS: "Series C+",
    FundingStage.UNKNOWN: "unknown-stage",
}
PERSONA_LABELS: Final = {
    Persona.CTO_FOUNDER: "CTO or a founder",
    Persona.ENG_LEADER: "VP of Engineering",
    Persona.AI_ML_LEAD: "head of AI/ML",
    Persona.FINANCE: "finance lead",
    Persona.PROCUREMENT: "procurement lead",
}
ELEMENT_LABELS: Final = {
    MEDDPICCElement.METRICS: "Metrics",
    MEDDPICCElement.ECONOMIC_BUYER: "Economic buyer",
    MEDDPICCElement.DECISION_CRITERIA: "Decision criteria",
    MEDDPICCElement.DECISION_PROCESS: "Decision process",
    MEDDPICCElement.PAPER_PROCESS: "Paper process",
    MEDDPICCElement.IDENTIFY_PAIN: "Identify pain",
    MEDDPICCElement.CHAMPION: "Champion",
    MEDDPICCElement.COMPETITION: "Competition",
}
WEDGE_LABELS: Final = {
    WedgeId.PROMPT_CACHING: "Prompt caching",
    WedgeId.EXTENDED_THINKING: "Extended thinking",
    WedgeId.CLOUD_DRAWDOWN: "Cloud marketplace",
}


def join(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"
