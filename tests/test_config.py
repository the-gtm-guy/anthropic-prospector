from pathlib import Path

import pytest
from pydantic import ValidationError

from anthropic_prospector.config import DEFAULT_MODEL, Settings, default_cache_dir, env_var_names

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_defaults_need_no_configuration() -> None:
    settings = Settings()
    assert not settings.has_anthropic_key
    assert settings.anthropic_api_key is None
    assert settings.anthropic_model == DEFAULT_MODEL == "claude-sonnet-5-5"
    assert settings.http_concurrency == 5
    assert settings.cache_dir == default_cache_dir()


def test_reads_third_party_names_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    settings = Settings()
    assert settings.has_anthropic_key
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test-123"
    assert settings.anthropic_model == "claude-opus-5-5"


def test_prefix_does_not_apply_to_third_party_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROSPECTOR_ANTHROPIC_API_KEY", "sk-ant-wrong-name")
    assert Settings().anthropic_api_key is None


def test_secrets_never_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    settings = Settings()
    for rendered in (repr(settings), str(settings), settings.model_dump_json()):
        assert "sk-ant-secret" not in rendered


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_values_count_as_unset(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", blank)
    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    monkeypatch.setenv("PROSPECTOR_HTTP_CONCURRENCY", "")
    settings = Settings()
    assert not settings.has_anthropic_key
    assert settings.anthropic_model == DEFAULT_MODEL
    assert settings.http_concurrency == 5


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PROSPECTOR_HTTP_CONCURRENCY", "0"),
        ("PROSPECTOR_HTTP_CONCURRENCY", "lots"),
        ("PROSPECTOR_HTTP_READ_TIMEOUT_S", "-1"),
        ("PROSPECTOR_CACHE_TTL_HOURS", "-2"),
    ],
)
def test_invalid_tunables_fail_loudly(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_cache_dir_follows_xdg_and_expands_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert Settings().cache_dir == tmp_path / "anthropic-prospector"
    monkeypatch.setenv("PROSPECTOR_CACHE_DIR", "~/prospector-cache")
    assert Settings().cache_dir == Path.home() / "prospector-cache"


def test_reads_dotenv_and_ignores_unrelated_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_MODEL=claude-haiku-5-5\nPROSPECTOR_HTTP_CONCURRENCY=3\nOPENAI_API_KEY=x\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "env_file", env_file)
    settings = Settings()
    assert settings.anthropic_model == "claude-haiku-5-5"
    assert settings.http_concurrency == 3


def test_copied_env_example_behaves_like_no_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = Settings()
    monkeypatch.setitem(Settings.model_config, "env_file", REPO_ROOT / ".env.example")
    assert Settings() == defaults


def test_env_example_documents_every_setting() -> None:
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    documented = {
        line.split("=", 1)[0].strip() for line in lines if line.strip() and not line.startswith("#")
    }
    assert documented == set(env_var_names())
