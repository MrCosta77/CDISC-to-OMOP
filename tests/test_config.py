from src.utils.config import env_text


def test_blank_model_configuration_uses_documented_default(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "   ")
    assert env_text("MODEL_NAME", "qwen2.5-coder:7b") == "qwen2.5-coder:7b"


def test_nonblank_model_configuration_is_trimmed(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "  local-model:latest  ")
    assert env_text("MODEL_NAME", "fallback") == "local-model:latest"
