"""utils/env_secrets .env 读写。"""
from utils.env_secrets import effective_secret, read_env_file, write_env_file


def test_write_and_read_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr("utils.env_secrets.env_file_path", lambda: env_path)

    write_env_file({"LLM_API_KEY": "sk-test-key", "LLM_MODEL_NAME": "qwen"})
    data = read_env_file()
    assert data["LLM_API_KEY"] == "sk-test-key"
    assert data["LLM_MODEL_NAME"] == "qwen"

    write_env_file({"LLM_API_KEY": None})
    data2 = read_env_file()
    assert "LLM_API_KEY" not in data2
    assert data2["LLM_MODEL_NAME"] == "qwen"


def test_effective_secret_prefers_ui(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "from-env")
    assert effective_secret("llm.api_key", "from-ui") == "from-ui"
    assert effective_secret("llm.api_key", "") == "from-env"
