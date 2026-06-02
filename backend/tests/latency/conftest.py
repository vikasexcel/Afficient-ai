"""Latency-suite local conftest.

The session-wide ``recorder`` fixture and the ``pytest_sessionfinish``
report writer live in the top-level ``tests/conftest.py`` so the
performance and latency suites share one report.
"""
