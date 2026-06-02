"""Correlation context — request_id / job_id / item_id threaded through logs.

A contextvars-backed store of correlation fields plus a logging filter that
stamps them onto every record. The point: a single live request or batch item
is traceable across *all* the log lines it produces — not just the call sites
that remember to pass ids by hand. The gateway middleware binds `request_id`
per request; the worker binds `job_id`/`item_id` around each item.

This is the whole of the platform's tracing story — correlation IDs in
structured logs, no OpenTelemetry (locked decision). IDs deliberately do NOT
become Prometheus labels: they're unbounded-cardinality values that would
blow up the metric series. Log → metric joins happen on status + time, with
the cause carried in the correlated log line.
"""

import contextlib
import contextvars
import logging
from collections.abc import Iterator

# None default (not {}): a mutable default is a footgun even though we only ever
# replace it, never mutate in place. get_correlation() normalizes None to empty.
_correlation: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "correlation", default=None
)


def get_correlation() -> dict[str, str]:
    """The correlation fields bound in the current context (possibly empty)."""
    return _correlation.get() or {}


def bind_correlation(**fields: str) -> contextvars.Token:
    """Merge `fields` into the current correlation context; returns a reset token."""
    return _correlation.set({**get_correlation(), **fields})


def reset_correlation(token: contextvars.Token) -> None:
    """Restore the correlation context to before the matching `bind_correlation`."""
    _correlation.reset(token)


@contextlib.contextmanager
def correlation_context(**fields: str) -> Iterator[None]:
    """Bind correlation `fields` for the duration of the block, then restore."""
    token = bind_correlation(**fields)
    try:
        yield
    finally:
        reset_correlation(token)


class CorrelationIdFilter(logging.Filter):
    """Stamp the current correlation fields onto each record so the formatter
    emits them.

    A logging Filter (not a Formatter) so it runs once per record regardless of
    formatter, and only fills in fields the call site didn't already set via
    `extra=` — an explicit value always wins.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in get_correlation().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True
