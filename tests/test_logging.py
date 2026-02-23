import logging

import pytest

from adrs_warehouse.utils.logging import setup_logging


@pytest.fixture(autouse=True)
def reset_adrs_logger():
    """Remove handlers before and after each test to keep logger state clean."""
    logger = logging.getLogger("adrs_warehouse")
    for h in logger.handlers[:]:
        h.close()
        logger.removeHandler(h)
    yield
    for h in logger.handlers[:]:
        h.close()
        logger.removeHandler(h)


class TestSetupLogging:
    def test_adds_file_and_console_handlers(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        setup_logging()
        logger = logging.getLogger("adrs_warehouse")
        assert len(logger.handlers) == 2

    def test_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        setup_logging()
        setup_logging()  # second call should be a no-op
        logger = logging.getLogger("adrs_warehouse")
        assert len(logger.handlers) == 2

    def test_custom_level_applied_to_console_handler(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        setup_logging(level=logging.WARNING)
        logger = logging.getLogger("adrs_warehouse")
        stream_handlers = [
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not hasattr(h, "baseFilename")
        ]
        assert stream_handlers[0].level == logging.WARNING

    def test_creates_log_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        setup_logging()
        assert (tmp_path / "logs").is_dir()
