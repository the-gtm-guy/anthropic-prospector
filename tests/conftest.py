import pytest

from anthropic_prospector.config import Settings, env_var_names


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sees the developer's real keys or .env file, so none can go live by accident."""
    for name in env_var_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
