"""The LLM boundary. The mock is free and offline; the live client runs against the real
Anthropic SDK over an in-memory transport (httpx2.MockTransport), so the request shape,
response parsing, the validation retry and error mapping are tested without a network."""

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from anthropic_prospector.config import Settings
from anthropic_prospector.models import LLMUsage, ObjectionHandle
from anthropic_prospector.pipeline.llm import (
    FALLBACK_BETA,
    AnthropicLLMClient,
    LLMError,
    LLMOutputError,
    LLMRefusalError,
    MockLLMClient,
    StructuredRequest,
    estimate_cost,
)

GOOD = ObjectionHandle(objection="We're busy this quarter.", response="Which quarter works?")
USAGE: dict[str, int] = {
    "input_tokens": 1000,
    "output_tokens": 500,
    "cache_read_input_tokens": 3000,
    "cache_creation_input_tokens": 0,
}


def _request(
    check: Callable[[ObjectionHandle], None] | None = None,
) -> StructuredRequest[ObjectionHandle]:
    if check is None:
        return StructuredRequest(
            schema=ObjectionHandle, system="SYSTEM", user="USER", deterministic=lambda: GOOD
        )
    return StructuredRequest(
        schema=ObjectionHandle,
        system="SYSTEM",
        user="USER",
        deterministic=lambda: GOOD,
        check=check,
    )


def _reply(
    text: str | None = None,
    *,
    stop_reason: str = "end_turn",
    model: str = "claude-sonnet-5-5",
) -> httpx2.Response:
    content = [] if text is None else [{"type": "text", "text": text}]
    body: dict[str, Any] = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": USAGE,
    }
    return httpx2.Response(200, json=body)


def _error(status: int, kind: str) -> httpx2.Response:
    return httpx2.Response(
        status, json={"type": "error", "error": {"type": kind, "message": "nope"}}
    )


class Recorder:
    """Replays canned responses in order and keeps every request."""

    def __init__(self, *responses: httpx2.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def body(self, n: int = 0) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.requests[n].content)
        return data


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response], model: str = "claude-sonnet-5-5"
) -> AnthropicLLMClient:
    http = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    sdk = anthropic.Anthropic(api_key="sk-ant-test", http_client=http, max_retries=0)
    return AnthropicLLMClient(model=model, client=sdk)


# --------------------------------------------------------------------------- mock


def test_mock_returns_the_deterministic_answer_for_free() -> None:
    mock = MockLLMClient()
    assert mock.model_id is None
    assert mock.generate(_request()) == (GOOD, LLMUsage())


def test_mock_still_runs_the_domain_check() -> None:
    def reject(_: ObjectionHandle) -> None:
        raise ValueError("rejected")

    with pytest.raises(ValueError, match="rejected"):
        MockLLMClient().generate(_request(reject))


# --------------------------------------------------------------------------- live client


def test_request_uses_cached_system_prompt_and_structured_output() -> None:
    recorder = Recorder(_reply(GOOD.model_dump_json()))
    answer, _ = _client(recorder).generate(_request())
    assert answer == GOOD

    request, body = recorder.requests[0], recorder.body()
    assert request.url.path == "/v1/messages"
    assert body["model"] == "claude-sonnet-5-5"
    assert body["system"] == [
        {"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["messages"] == [{"role": "user", "content": "USER"}]
    schema_format = body["output_config"]["format"]
    assert schema_format["type"] == "json_schema"
    assert schema_format["schema"]["additionalProperties"] is False
    objection = schema_format["schema"]["properties"]["objection"]
    assert "minLength" not in objection  # moved into the description; enforced client-side
    # Forced tool use returns a 400 on current models; thinking is left at the model default.
    assert not {"tools", "tool_choice", "thinking"} & body.keys()
    assert body["fallbacks"] == "default"
    assert FALLBACK_BETA in request.headers["anthropic-beta"]


def test_usage_and_cost_are_reported() -> None:
    _, usage = _client(Recorder(_reply(GOOD.model_dump_json()))).generate(_request())
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (1000, 500, 3000)
    # Claude Sonnet 5.5: $2 input, $10 output, $0.20 cache reads per million tokens.
    assert usage.est_cost_usd == pytest.approx((1000 * 2 + 500 * 10 + 3000 * 0.2) / 1e6)


def test_an_invalid_answer_is_retried_with_the_error() -> None:
    recorder = Recorder(
        _reply('{"objection": "", "response": "x"}'), _reply(GOOD.model_dump_json())
    )
    answer, usage = _client(recorder).generate(_request())
    assert answer == GOOD
    retry = recorder.body(1)["messages"]
    assert [m["role"] for m in retry] == ["user", "assistant", "user"]
    assert "failed validation" in retry[2]["content"]
    assert "objection" in retry[2]["content"]
    assert usage.input_tokens == 2000  # both attempts are counted


def test_a_failing_domain_check_gives_up_after_one_retry() -> None:
    def reject(_: ObjectionHandle) -> None:
        raise ValueError("cites evidence ids that do not exist: E9")

    recorder = Recorder(_reply(GOOD.model_dump_json()), _reply(GOOD.model_dump_json()))
    with pytest.raises(LLMOutputError, match=r"failed validation twice.*E9") as caught:
        _client(recorder).generate(_request(reject))
    assert len(recorder.requests) == 2
    assert caught.value.usage.input_tokens == 2000


def test_refusals_and_truncation_are_errors() -> None:
    with pytest.raises(LLMRefusalError):
        _client(Recorder(_reply(stop_reason="refusal"))).generate(_request())
    with pytest.raises(LLMOutputError, match="cut off"):
        _client(Recorder(_reply('{"objection": "x"', stop_reason="max_tokens"))).generate(
            _request()
        )


@pytest.mark.parametrize(
    ("response", "transient"),
    [
        (_error(429, "rate_limit_error"), True),
        (_error(529, "overloaded_error"), True),
        (_error(400, "invalid_request_error"), False),
        (_error(401, "authentication_error"), False),
    ],
)
def test_api_errors_say_whether_to_retry(response: httpx2.Response, transient: bool) -> None:
    with pytest.raises(LLMError) as caught:
        _client(Recorder(response)).generate(_request())
    assert caught.value.transient is transient


def test_network_failures_are_transient() -> None:
    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(LLMError, match="unreachable") as caught:
        _client(unreachable).generate(_request())
    assert caught.value.transient


def test_fallbacks_are_only_sent_to_models_that_support_them() -> None:
    recorder = Recorder(_reply(GOOD.model_dump_json(), model="claude-haiku-5-5"))
    _client(recorder, model="claude-haiku-5-5").generate(_request())
    assert "fallbacks" not in recorder.body()
    assert FALLBACK_BETA not in recorder.requests[0].headers.get("anthropic-beta", "")


def test_a_fallback_answer_is_priced_by_the_model_that_served_it() -> None:
    recorder = Recorder(_reply(GOOD.model_dump_json(), model="claude-opus-5-5"))
    _, usage = _client(recorder).generate(_request())
    assert usage.est_cost_usd == pytest.approx((1000 * 4 + 500 * 20 + 3000 * 0.2) / 1e6)


def test_from_settings_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicLLMClient.from_settings(Settings())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    assert AnthropicLLMClient.from_settings(Settings()).model_id == "claude-opus-5-5"


def test_cost_of_an_unknown_model_is_zero() -> None:
    assert estimate_cost("claude-unknown", input_tokens=10_000, output_tokens=10_000) == 0.0
