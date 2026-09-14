import logging

import pytest
import structlog


@pytest.fixture(autouse=True)
def isolate_auth_env(monkeypatch):
    monkeypatch.setenv("CC_ADAPTER_ACCESS_KEY", "")
    monkeypatch.setenv("CC_ADAPTER_ADMIN_PASSWORD", "")


@pytest.fixture(autouse=True, scope="session")
def isolate_runtime_data_dir(tmp_path_factory):
    """Keep runtime data files (cli_version.json, token_usage.json, models_cache.json) out of the repo.

    They default to `data_dir()`, i.e. next to CC_ADAPTER_ENV_FILE, which is the working
    directory when that variable is unset - a test that lets a real (or respx-mocked)
    fetch complete would otherwise drop files into the repository. Tests that assert the
    default location override the variable themselves (see tests/test_data_dir.py).
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("CC_ADAPTER_ENV_FILE", str(tmp_path_factory.mktemp("cc-adapter-data") / ".env"))
    yield
    monkeypatch.undo()


@pytest.fixture(autouse=True, scope="session")
def configure_structlog_for_tests():
    """Configure structlog to use stdlib logging for caplog/capsys capture."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    # Ensure there's a handler so logs go through stdlib
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    root.setLevel(logging.DEBUG)
