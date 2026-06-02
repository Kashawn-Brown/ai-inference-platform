"""Unit tests for the correlation context and its logging filter."""

import logging

from aiinfra.observability.context import (
    CorrelationIdFilter,
    bind_correlation,
    correlation_context,
    get_correlation,
    reset_correlation,
)


def _record() -> logging.LogRecord:
    return logging.makeLogRecord({"msg": "x"})


def test_bind_and_reset_restores_previous_context():
    assert get_correlation() == {}
    token = bind_correlation(request_id="r1")
    assert get_correlation() == {"request_id": "r1"}

    reset_correlation(token)
    assert get_correlation() == {}


def test_correlation_context_merges_and_restores():
    with correlation_context(job_id="j", item_id="i"):
        assert get_correlation() == {"job_id": "j", "item_id": "i"}
    assert get_correlation() == {}


def test_filter_stamps_bound_fields_onto_record():
    f = CorrelationIdFilter()
    with correlation_context(request_id="abc"):
        record = _record()
        f.filter(record)
    assert record.request_id == "abc"


def test_filter_adds_nothing_when_unbound():
    f = CorrelationIdFilter()
    record = _record()

    f.filter(record)

    assert not hasattr(record, "request_id")


def test_filter_does_not_clobber_explicit_field():
    f = CorrelationIdFilter()
    with correlation_context(request_id="ctx"):
        record = _record()
        record.request_id = "explicit"  # e.g. set via extra= at the call site
        f.filter(record)
    assert record.request_id == "explicit"
