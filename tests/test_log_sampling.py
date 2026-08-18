"""
Test suite for log sampling (issue #15).

Covers: SamplingFilter's per-operation-type counter, the always-log
guarantee for WARNING/ERROR/CRITICAL, the default (no sampling) behavior,
and wiring through Config -> setup_logging.
"""

import logging

from universal_memory_mcp.logging_config import SamplingFilter, _get_log_sample_rates, setup_logging


def _make_record(level=logging.INFO, context=None):
    record = logging.LogRecord("test", level, __file__, 1, "message", None, None)
    if context is not None:
        record.context = context
    return record


class TestSamplingFilterDefaults:
    def test_no_rates_configured_always_logs(self):
        f = SamplingFilter()
        for _ in range(50):
            assert f.filter(_make_record(context={"type": "performance"})) is True

    def test_unconfigured_type_always_logs(self):
        f = SamplingFilter({"performance": 10})
        for _ in range(50):
            assert f.filter(_make_record(context={"type": "file_operation"})) is True

    def test_record_without_context_uses_default_bucket(self):
        f = SamplingFilter({"default": 2})
        results = [f.filter(_make_record()) for _ in range(4)]
        # Kept every 2nd: False, True, False, True
        assert results == [False, True, False, True]


class TestSamplingFilterRateBehavior:
    def test_samples_every_nth_record(self):
        f = SamplingFilter({"performance": 10})
        results = [f.filter(_make_record(context={"type": "performance"})) for _ in range(30)]
        kept_indexes = [i for i, kept in enumerate(results, start=1) if kept]
        assert kept_indexes == [10, 20, 30]

    def test_rate_of_one_is_always_logged(self):
        f = SamplingFilter({"performance": 1})
        for _ in range(10):
            assert f.filter(_make_record(context={"type": "performance"})) is True

    def test_counters_are_independent_per_type(self):
        f = SamplingFilter({"performance": 2, "file_operation": 3})
        perf_results = [f.filter(_make_record(context={"type": "performance"})) for _ in range(4)]
        file_results = [
            f.filter(_make_record(context={"type": "file_operation"})) for _ in range(3)
        ]
        assert perf_results == [False, True, False, True]
        assert file_results == [False, False, True]


class TestSamplingNeverDropsWarningsOrErrors:
    def test_warning_always_logged_even_at_high_sample_rate(self):
        f = SamplingFilter({"performance": 1000})
        for _ in range(10):
            assert f.filter(_make_record(logging.WARNING, {"type": "performance"})) is True

    def test_error_always_logged_even_at_high_sample_rate(self):
        f = SamplingFilter({"performance": 1000})
        for _ in range(10):
            assert f.filter(_make_record(logging.ERROR, {"type": "performance"})) is True

    def test_critical_always_logged(self):
        f = SamplingFilter({"performance": 1000})
        assert f.filter(_make_record(logging.CRITICAL, {"type": "performance"})) is True

    def test_error_logged_does_not_consume_the_info_counter(self):
        f = SamplingFilter({"performance": 3})
        # Two INFO records shouldn't yet trigger a keep at rate 3.
        assert f.filter(_make_record(logging.INFO, {"type": "performance"})) is False
        assert f.filter(_make_record(logging.INFO, {"type": "performance"})) is False
        # A flood of ERRORs in between must not perturb the INFO counter.
        for _ in range(20):
            f.filter(_make_record(logging.ERROR, {"type": "performance"}))
        # Third INFO record completes the cycle of 3 and is kept.
        assert f.filter(_make_record(logging.INFO, {"type": "performance"})) is True


class TestConfigWiring:
    def test_get_log_sample_rates_reads_from_config(self):
        from universal_memory_mcp.config import Config

        cfg = Config(log_sample_rates={"performance": 5})
        assert _get_log_sample_rates(cfg) == {"performance": 5}

    def test_get_log_sample_rates_defaults_to_empty_dict_with_no_env(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_MCP_LOG_SAMPLE_RATES", raising=False)
        assert _get_log_sample_rates(None) == {}

    def test_get_log_sample_rates_swallows_malformed_config(self):
        class _Broken:
            @property
            def log_sample_rates(self):
                raise RuntimeError("boom")

        # Never let a malformed config bring down logging setup.
        assert _get_log_sample_rates(_Broken()) == {}

    def test_setup_logging_attaches_sampling_filter(self, tmp_path):
        # NOTE: this used to assert the filter lived on `logger.filters`.
        # That encoded the bug this suite's sibling (test_logging_wiring.py)
        # exists to catch: a logger's own filters never run for records that
        # reach its handlers via propagation from a child logger (the
        # pattern this app actually uses via get_logger()). The fix moves
        # sampling to per-handler filters, so the assertion now checks the
        # handlers instead.
        from universal_memory_mcp.config import Config

        cfg = Config(log_sample_rates={"performance": 7}, console_output=False)
        logger = setup_logging(
            config=cfg, log_file=str(tmp_path / "test.log"), console_output=False
        )
        assert logger.filters == []
        for handler in logger.handlers:
            sampling_filters = [f for f in handler.filters if isinstance(f, SamplingFilter)]
            assert len(sampling_filters) == 1
            assert sampling_filters[0].sample_rates == {"performance": 7}

    def test_setup_logging_default_config_disables_sampling(self, tmp_path):
        logger = setup_logging(log_file=str(tmp_path / "test.log"), console_output=False)
        assert logger.filters == []
        for handler in logger.handlers:
            sampling_filters = [f for f in handler.filters if isinstance(f, SamplingFilter)]
            assert len(sampling_filters) == 1
            assert sampling_filters[0].sample_rates == {}
