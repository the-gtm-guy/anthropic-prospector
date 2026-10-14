"""The LLM boundary: one Protocol, a deterministic mock, and the live Anthropic client.

Pipeline code describes each LLM task as a StructuredRequest: the shared system prompt,
the account-specific user turn, the output schema, a deterministic rules-based answer, and
a domain check. Any LLMClient turns that into a validated model:

* MockLLMClient returns the deterministic answer: no network, no key, zero cost.
* AnthropicLLMClient asks Claude for the same schema with structured outputs. The API
  enforces the JSON shape; constraints its schema subset cannot express (string lengths,
  item counts, numeric bounds) are checked here, and a failing answer gets one retry with
  the error before LLMOutputError. Forced tool_choice is deliberately not used: current
  models (Claude Sonnet 5.5, Claude Opus 5.5) reject it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Generic, Protocol, TypeVar

import anthropic
from anthropic.types.beta import BetaMessage, BetaTextBlock
from pydantic import BaseModel

from anthropic_prospector.config import DEFAULT_MODEL, Settings
from anthropic_prospector.models import LLMUsage

T = TypeVar("T", bound=BaseModel)

# Server-side refusal fallbacks ("default" form). Claude API only, and only these models.
FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
FALLBACK_MODELS: Final = frozenset(
    {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
)


@dataclass(frozen=True)
class Price:
    """USD per million tokens, first-party Claude API list prices as of 2026-10."""

    input: float
    output: float
    cache_read: float
    cache_write: float  # 5-minute TTL: 1.25x input


PRICES: Final = {
    "claude-sonnet-5-5": Price(2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": Price(4.00, 20.00, 0.20, 5.00),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01, 0.125),  # prompts up to 100K tokens
    "claude-fable-5-1": Price(10.00, 50.00, 0.25, 12.50),
    "claude-opus-5": Price(5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5": Price(2.00, 10.00, 0.20, 2.50),
}


def estimate_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Estimated USD cost; 0.0 for a model without a known price."""
    price = PRICES.get(model)
    if price is None:
        return 0.0
    total = (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_read_tokens * price.cache_read
        + cache_write_tokens * price.cache_write
    )
    return total / 1_000_000


def _accept(_: Any) -> None:
    return None


@dataclass(frozen=True)
class StructuredRequest(Generic[T]):
    schema: type[T]
    system: str  # identical across accounts, so it is a cacheable prefix
    user: str  # account-specific; scraped text is already fenced and neutralized
    deterministic: Callable[[], T]  # the rules-based answer: what the mock returns
    check: Callable[[T], None] = _accept  # domain rules; raise ValueError to reject
    max_tokens: int = 16_000  # generous: adaptive thinking counts toward it


class LLMClient(Protocol):
    @property
    def model_id(self) -> str | None:
        """The model behind the answers, or None for the deterministic mock."""
        ...

    def generate(self, request: StructuredRequest[T]) -> tuple[T, LLMUsage]: ...


class LLMError(Exception):
    def __init__(
        self, message: str, *, transient: bool = False, usage: LLMUsage | None = None
    ) -> None:
        super().__init__(message)
        self.transient = transient  # worth retrying later (rate limit, overload, network)
        self.usage = usage or LLMUsage()  # tokens already spent before the failure


class LLMRefusalError(LLMError):
    """Claude declined the request (stop_reason "refusal")."""


class LLMOutputError(LLMError):
    """The answer was cut off or failed validation after the retry."""


class MockLLMClient:
    """Returns each request's deterministic answer: no network, no key, zero cost."""

    @property
    def model_id(self) -> str | None:
        return None

    def generate(self, request: StructuredRequest[T]) -> tuple[T, LLMUsage]:
        answer = request.deterministic()
        request.check(answer)
        return answer, LLMUsage()


class AnthropicLLMClient:
    """Claude through the Messages API, with a cached system prompt and structured outputs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        client: anthropic.Anthropic | None = None,
        max_retries: int = 3,
        timeout_s: float = 300.0,  # adaptive thinking can make a 16k-token answer slow
    ) -> None:
        if client is None:
            if not api_key:
                raise ValueError("the live client needs an Anthropic API key")
            client = anthropic.Anthropic(
                api_key=api_key, max_retries=max_retries, timeout=timeout_s
            )
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "AnthropicLLMClient":
        if settings.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        return cls(
            api_key=settings.anthropic_api_key.get_secret_value(), model=settings.anthropic_model
        )

    @property
    def model_id(self) -> str | None:
        return self._model

    def generate(self, request: StructuredRequest[T]) -> tuple[T, LLMUsage]:
        name = request.schema.__name__
        schema = anthropic.transform_schema(request.schema.model_json_schema())
        messages: list[Any] = [{"role": "user", "content": request.user}]
        usage = LLMUsage()
        problem = ""
        for _ in range(2):
            response = self._create(request, schema, messages, usage)
            usage = usage + self._usage(response)
            if response.stop_reason == "refusal":
                raise LLMRefusalError(f"Claude declined the {name} request", usage=usage)
            if response.stop_reason == "max_tokens":
                raise LLMOutputError(
                    f"{name} answer was cut off at max_tokens={request.max_tokens}", usage=usage
                )
            text = next((b.text for b in response.content if isinstance(b, BetaTextBlock)), "")
            try:
                answer = request.schema.model_validate_json(text)
                request.check(answer)
            except ValueError as exc:  # includes pydantic.ValidationError
                problem = str(exc)
                messages += [
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": f"That answer failed validation:\n{problem}\n"
                        "Reply again with the complete, corrected JSON object.",
                    },
                ]
                continue
            return answer, usage
        raise LLMOutputError(f"{name} answer failed validation twice: {problem}", usage=usage)

    def _create(
        self,
        request: StructuredRequest[T],
        schema: dict[str, Any],
        messages: list[Any],
        usage: LLMUsage,
    ) -> BetaMessage:
        fallbacks = self._model in FALLBACK_MODELS
        try:
            return self._client.beta.messages.create(
                model=self._model,
                max_tokens=request.max_tokens,
                system=[
                    {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
                ],
                messages=messages,
                output_config={"format": {"type": "json_schema", "schema": schema}},
                betas=[FALLBACK_BETA] if fallbacks else anthropic.omit,
                fallbacks="default" if fallbacks else anthropic.omit,
            )
        except anthropic.APIStatusError as exc:
            transient = exc.status_code == 429 or exc.status_code >= 500
            raise LLMError(
                f"Claude API error {exc.status_code}: {exc.message}",
                transient=transient,
                usage=usage,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Claude API unreachable: {exc}", transient=True, usage=usage) from exc

    def _usage(self, response: BetaMessage) -> LLMUsage:
        tokens = response.usage
        read = tokens.cache_read_input_tokens or 0
        write = tokens.cache_creation_input_tokens or 0
        # A refusal fallback can serve the answer from another model; price what ran.
        model = response.model if response.model in PRICES else self._model
        return LLMUsage(
            input_tokens=tokens.input_tokens,
            output_tokens=tokens.output_tokens,
            cache_read_tokens=read,
            cache_write_tokens=write,
            est_cost_usd=estimate_cost(
                model,
                input_tokens=tokens.input_tokens,
                output_tokens=tokens.output_tokens,
                cache_read_tokens=read,
                cache_write_tokens=write,
            ),
        )
