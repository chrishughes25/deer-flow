"""Tests for trusted-internal run reads in the thread_runs router.

AlphaFRS polls run status via GET /api/threads/{thread_id}/runs/{run_id}. Its
runs are created without an owner, and with multiple gateway workers a run may
live only in another worker's in-memory RunManager — so an owner-scoped store
lookup would 404 spuriously. The route reads unscoped for trusted internal
callers (thread-level owner_check still gates access).
"""

from types import SimpleNamespace

from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE
from app.gateway.routers.thread_runs import _is_trusted_internal_caller


def _request_with_user(user):
    return SimpleNamespace(state=SimpleNamespace(user=user))


def test_internal_token_caller_is_trusted():
    user = SimpleNamespace(id="svc", system_role=INTERNAL_SYSTEM_ROLE)
    assert _is_trusted_internal_caller(_request_with_user(user)) is True


def test_regular_user_is_not_trusted():
    user = SimpleNamespace(id="u1", system_role=None)
    assert _is_trusted_internal_caller(_request_with_user(user)) is False


def test_anonymous_request_is_not_trusted():
    assert _is_trusted_internal_caller(_request_with_user(None)) is False


def test_request_without_state_is_not_trusted():
    assert _is_trusted_internal_caller(SimpleNamespace()) is False
