"""Regression tests for security hardening.

poligloti has no login (see PRIVACY.md), so these keep the damage small when
someone who should not reaches the port, or when a model answers something
unexpected.
"""

from __future__ import annotations

from tests.test_api import _start, client  # noqa: F401  (shared fixture)


def test_session_start_does_not_return_the_system_prompt(client):  # noqa: F811
    data = _start(client)
    assert "system_prompt" not in data
    # Not even fragments: the memory block carries the level from USER.md.
    assert "cefr_estimate" not in str(data)
