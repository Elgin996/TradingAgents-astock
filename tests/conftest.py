"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")
    # pytest's default temp root is ACL-protected on this managed Windows
    # image. Point direct tempfile.mkdtemp() users at a normal workspace tree.
    system_tmp = Path.cwd() / ".pytest-system-temp"
    system_tmp.mkdir(exist_ok=True)
    tempfile.tempdir = str(system_tmp)

    def workspace_mkdtemp(suffix=None, prefix="tmp", dir=None):
        parent = Path(dir) if dir else system_tmp
        parent.mkdir(parents=True, exist_ok=True)
        name = f"{prefix or 'tmp'}{uuid.uuid4().hex[:8]}{suffix or ''}"
        path = parent / name
        path.mkdir()
        return str(path)

    tempfile.mkdtemp = workspace_mkdtemp


@pytest.fixture()
def tmp_path(request):
    """Workspace-local replacement for pytest's Windows-inaccessible tmpdir.

    The managed runner denies scanning the per-user temp directory and may
    deny pytest's cleanup pass as well. Test data is intentionally isolated in
    a uniquely named workspace directory; CI outside this runner can use the
    standard fixture by removing ``-p no:tmpdir`` and this override.
    """
    root = Path.cwd() / ".pytest-fixtures"
    root.mkdir(exist_ok=True)
    safe_name = "".join(char if char.isalnum() else "_" for char in request.node.name)[:60]
    path = root / f"{safe_name}-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    yield path


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "ZHIPU_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        monkeypatch.setenv(env_var, os.environ.get(env_var, "placeholder"))


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client
