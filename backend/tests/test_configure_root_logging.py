"""Tests for ``configure_root_logging`` — split-stream routing so container
platforms (Railway et al.) don't misclassify INFO logs (written to stderr by the
stdlib default) as errors. INFO/DEBUG must go to stdout; WARNING+ to stderr."""

import io
import logging

from deerflow.config.app_config import apply_logging_level, configure_root_logging


class TestConfigureRootLogging:
    """Verifies the root logger routes sub-WARNING to stdout and WARNING+ to stderr."""

    def setup_method(self) -> None:
        root = logging.root
        self._orig_level = root.level
        self._orig_handlers = list(root.handlers)
        self._orig_deerflow_level = logging.getLogger("deerflow").level

    def teardown_method(self) -> None:
        root = logging.root
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in self._orig_handlers:
            root.addHandler(handler)
        root.setLevel(self._orig_level)
        logging.getLogger("deerflow").setLevel(self._orig_deerflow_level)

    @staticmethod
    def _capture() -> tuple[io.StringIO, io.StringIO]:
        """Swap the two split handlers' streams for buffers, keyed by which one
        passes an INFO record (stdout) vs not (stderr). Independent of pytest's
        own stdout/stderr capture."""
        out, err = io.StringIO(), io.StringIO()
        probe = logging.LogRecord("probe", logging.INFO, __file__, 0, "", None, None)
        for handler in logging.root.handlers:
            if handler.filter(probe):
                handler.setStream(out)
            else:
                handler.setStream(err)
        return out, err

    def test_info_goes_to_stdout_only(self) -> None:
        configure_root_logging()
        out, err = self._capture()
        logging.getLogger("httpx").info("HTTP Request: POST https://api.deepseek.com 200 OK")
        assert "200 OK" in out.getvalue()
        assert "200 OK" not in err.getvalue()

    def test_warning_and_error_go_to_stderr_only(self) -> None:
        configure_root_logging()
        out, err = self._capture()
        logging.getLogger("deerflow.x").warning("a-warning")
        logging.getLogger("deerflow.x").error("an-error")
        assert "a-warning" in err.getvalue()
        assert "an-error" in err.getvalue()
        assert "a-warning" not in out.getvalue()
        assert "an-error" not in out.getvalue()

    def test_apply_logging_level_does_not_leak_info_to_stderr(self) -> None:
        """apply_logging_level lowers handler levels; the split must survive it
        (enforced by filters, not handler levels) so INFO never reaches stderr."""
        configure_root_logging()
        apply_logging_level("info")
        out, err = self._capture()
        logging.getLogger("deerflow.y").info("no-leak")
        assert "no-leak" in out.getvalue()
        assert "no-leak" not in err.getvalue()

    def test_idempotent_leaves_exactly_two_handlers(self) -> None:
        configure_root_logging()
        configure_root_logging()
        handlers = logging.root.handlers
        assert len(handlers) == 2
        probe = logging.LogRecord("p", logging.INFO, __file__, 0, "", None, None)
        passes_info = [h for h in handlers if h.filter(probe)]
        assert len(passes_info) == 1  # exactly one stdout (INFO) + one stderr handler

    def test_default_root_level_is_info(self) -> None:
        configure_root_logging()
        assert logging.root.level == logging.INFO

    def test_respects_explicit_level_name(self) -> None:
        configure_root_logging("warning")
        assert logging.root.level == logging.WARNING
