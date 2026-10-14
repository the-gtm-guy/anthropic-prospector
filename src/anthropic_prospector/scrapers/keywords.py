"""Signal vocabularies: the patterns that turn job posts and web pages into signals.

Every pattern is case-insensitive and word-bounded. Ambiguous words never count alone:
"Lambda" needs "AWS", "Bedrock" needs "Amazon" or "AWS", "reasoning" needs a qualifier,
and "OpenAI" inside "Azure OpenAI" counts only as Azure OpenAI. Matches are reported per
sentence, so each signal can cite the sentence it came from.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Final, TypeVar

from anthropic_prospector.models import (
    SNIPPET_MAX_CHARS,
    CloudProvider,
    CompetitorKind,
    SignalKeyword,
    clip,
)

_K = TypeVar("_K")


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


KEYWORD_PATTERNS: Final[dict[SignalKeyword, re.Pattern[str]]] = {
    SignalKeyword.RAG: _rx(
        r"\b(rag|retrieval[- ]augmented|vector (search|databases?|db|stores?)|embeddings?|"
        r"pgvector|pinecone|weaviate|semantic search|re-?ranking)\b"
    ),
    SignalKeyword.AGENTS: _rx(
        r"\b(ai agents?|llm agents?|agentic|autonomous agents?|multi-agent|tool[- ]use|"
        r"tool calling|function calling|build(ing)? agents?|agents that)\b"
    ),
    SignalKeyword.EVALS: _rx(
        r"\b(evals?|evaluation (suites?|harness(es)?|frameworks?|sets?|pipelines?)|"
        r"llm[- ]as[- ]an?[- ]judge|golden (sets?|datasets?))\b"
    ),
    SignalKeyword.CODE_GENERATION: _rx(
        r"\b(code generation|code review|coding (assistants?|agents?)|text[- ]to[- ]sql|"
        r"sql generation|write sql|writes sql)\b"
    ),
    SignalKeyword.DOCUMENT_PROCESSING: _rx(
        r"\b(document (understanding|processing|extraction|parsing|ai|intelligence)|"
        r"intelligent document processing|ocr|invoice (processing|extraction)|"
        r"clause (extraction|classification)|pdf (parsing|extraction)|extract line items)\b"
    ),
    SignalKeyword.LONG_CONTEXT: _rx(
        r"\b(long[- ]context|long documents?|lengthy documents?|context windows?|"
        r"whole (repositories|codebases?)|full agreements?|\d{2,4}\+?[- ]page)\b"
    ),
    SignalKeyword.CUSTOMER_SUPPORT: _rx(
        r"\b(customer support|support (tickets?|automation|agents?)|help ?desk|"
        r"ticket (deflection|resolution)|contact cent(er|re))\b"
    ),
    SignalKeyword.MULTI_STEP_REASONING: _rx(
        r"\b(multi[- ]step (reasoning|tasks?|workflows?|agents?|planning)|complex reasoning|"
        r"reasoning (models?|quality|tasks?)|chain[- ]of[- ]thought|self[- ]verification)\b"
    ),
    SignalKeyword.INFERENCE_COST: _rx(
        r"\b(inference (costs?|spend|budgets?)|cost per (call|request|token|query|document|"
        r"session|note|ticket)|token (costs?|spend|budgets?)|llm (costs?|spend)|gpu (costs?|spend)|"
        r"cost dashboards?)\b"
    ),
    SignalKeyword.LATENCY: _rx(
        r"\b(latency|p9[059] latency|time[- ]to[- ]first[- ]token|ttft|real[- ]time inference)\b"
    ),
    SignalKeyword.FINE_TUNING: _rx(
        r"\b(fine[- ]?tun(e|es|ed|ing)|lora|qlora|rlhf|post[- ]training)\b"
    ),
    SignalKeyword.SELF_HOSTED_MODELS: _rx(
        r"\b(self[- ]host(ed|ing)? (models?|llms?|inference)|open[- ]weights? models?|"
        r"open[- ]source (llms?|models?)|serve (fine-tuned )?open[- ]weight|vllm|"
        r"text generation inference|ollama)\b"
    ),
    SignalKeyword.GPU_INFRA: _rx(
        r"\b(gpus?|gpu fleet|cuda|a100s?|h100s?|h200s?|tensorrt|triton inference server)\b"
    ),
    SignalKeyword.COMPLIANCE: _rx(
        r"\b(soc ?[12]|hipaa|iso ?27001|gdpr|fedramp|pci[- ]dss|security (reviews?|"
        r"questionnaires?)|data residency)\b"
    ),
}

_AZURE_OPENAI: Final = _rx(r"\bazure[- ]open ?ai( service)?\b")

COMPETITOR_PATTERNS: Final[dict[CompetitorKind, re.Pattern[str]]] = {
    CompetitorKind.AZURE_OPENAI: _AZURE_OPENAI,
    CompetitorKind.OPENAI: _rx(r"\b(open ?ai|chat ?gpt|gpt-?(3\.5|4o?|4\.1|5)(-[a-z0-9]+)?)\b"),
    CompetitorKind.LANGCHAIN: _rx(r"\b(langchain|langgraph|langsmith)\b"),
    CompetitorKind.VLLM: _rx(r"\bvllm\b"),
    CompetitorKind.OTHER_LLM: _rx(r"\b(gemini|cohere|mistral( ai)?|llama( ?\d+(\.\d+)?)?)\b"),
    CompetitorKind.ANTHROPIC_EXISTING: _rx(r"\b(anthropic|claude)\b"),
}

CLOUD_PATTERNS: Final[dict[CloudProvider, re.Pattern[str]]] = {
    CloudProvider.AWS: _rx(
        r"\b(aws|amazon web services|ec2|eks|ecs|aws lambda|s3|sagemaker|dynamodb|"
        r"amazon bedrock|aws bedrock|cloudfront)\b"
    ),
    CloudProvider.GCP: _rx(
        r"\b(gcp|google cloud( platform)?|bigquery|cloud run|gke|vertex ai|cloud functions|"
        r"firestore)\b"
    ),
    CloudProvider.AZURE: _rx(r"\b(azure|aks|cosmos ?db)\b"),
}

_AI_TITLE: Final = _rx(
    r"\b(ai|ml|machine learning|llm|nlp|genai|generative ai|deep learning|applied scientist|"
    r"research (engineer|scientist)|data scientist|prompt engineer|inference)\b"
)
_LLM_TERMS: Final = _rx(
    r"\b(llms?|large language models?|generative ai|genai|foundation models?)\b"
)
_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Mention:
    term: str  # the matched text, as written
    sentence: str  # the sentence around it, clipped to snippet length


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def _scan(text: str, patterns: dict[_K, re.Pattern[str]]) -> dict[_K, list[Mention]]:
    found: dict[_K, list[Mention]] = defaultdict(list)
    for sentence in sentences(text):
        azure = [m.span() for m in _AZURE_OPENAI.finditer(sentence)]
        for key, pattern in patterns.items():
            for match in pattern.finditer(sentence):
                inside_azure = any(a <= match.start() and match.end() <= b for a, b in azure)
                if key == CompetitorKind.OPENAI and inside_azure:
                    continue
                found[key].append(Mention(match.group(0), clip(sentence, SNIPPET_MAX_CHARS)))
                break  # one mention per key per sentence
    return dict(found)


def find_keywords(text: str) -> dict[SignalKeyword, list[Mention]]:
    return _scan(text, KEYWORD_PATTERNS)


def find_competitors(text: str) -> dict[CompetitorKind, list[Mention]]:
    return _scan(text, COMPETITOR_PATTERNS)


def find_clouds(text: str) -> dict[CloudProvider, list[Mention]]:
    return _scan(text, CLOUD_PATTERNS)


def is_ai_role(title: str, description: str = "") -> bool:
    """An AI/ML job: by title, or an engineering role whose posting centres on LLM work."""
    return bool(_AI_TITLE.search(title)) or len(_LLM_TERMS.findall(description)) >= 2
