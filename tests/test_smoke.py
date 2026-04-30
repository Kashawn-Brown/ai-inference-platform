"""Sentinel smoke test.

Pytest exits with code 5 when no tests are collected, which CI treats as
failure. This single test catches that and also verifies that the gateway
and worker entrypoints import cleanly — broken imports anywhere in the
package surface here.
"""


def test_entrypoints_import():
    import aiinfra.gateway.main
    import aiinfra.worker.main

    assert aiinfra.gateway.main.app is not None
    assert aiinfra.worker.main.main is not None
