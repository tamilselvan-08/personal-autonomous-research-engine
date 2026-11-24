import logging
import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import Settings, get_settings
from app.core.logging import JsonFormatter, redact
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.domain import task_state
from app.models import TaskStatus


class TestTaskStateMachine:
    def test_every_status_has_a_transition_entry(self) -> None:
        assert set(task_state.ALLOWED_TRANSITIONS) == set(TaskStatus)

    def test_draft_can_only_go_to_planning(self) -> None:
        assert task_state.allowed_transitions(TaskStatus.DRAFT) == [TaskStatus.PLANNING]

    def test_execution_requires_approval_path(self) -> None:
        # There is no route from draft/awaiting_approval straight to queued/running.
        for src in (TaskStatus.DRAFT, TaskStatus.PLANNING, TaskStatus.AWAITING_APPROVAL):
            assert not task_state.can_transition(src, TaskStatus.QUEUED)
            assert not task_state.can_transition(src, TaskStatus.RUNNING)
        assert task_state.can_transition(TaskStatus.APPROVED, TaskStatus.QUEUED)

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(task_state.InvalidTransitionError):
            task_state.assert_transition(TaskStatus.CANCELLED, TaskStatus.RUNNING)

    @pytest.mark.parametrize(
        ("status", "editable", "deletable"),
        [
            (TaskStatus.DRAFT, True, True),
            (TaskStatus.AWAITING_APPROVAL, False, True),
            (TaskStatus.RUNNING, False, False),
            (TaskStatus.PAUSED, False, False),
            (TaskStatus.QUEUED, False, False),
            (TaskStatus.COMPLETED, False, True),
        ],
    )
    def test_edit_and_delete_rules(
        self, status: TaskStatus, editable: bool, deletable: bool
    ) -> None:
        assert task_state.is_editable(status) is editable
        assert task_state.is_deletable(status) is deletable


class TestPasswords:
    def test_hash_and_verify(self) -> None:
        hashed = hash_password("correct-horse-42", rounds=4)
        assert hashed != "correct-horse-42"
        assert verify_password("correct-horse-42", hashed)
        assert not verify_password("wrong-horse-42", hashed)

    def test_verify_handles_garbage_hash(self) -> None:
        assert verify_password("x", "not-a-bcrypt-hash") is False


class TestTokens:
    def test_round_trip(self) -> None:
        settings = get_settings()
        uid = uuid.uuid4()
        token, expires = create_access_token(settings, uid, 3)
        claims = decode_access_token(settings, token)
        assert claims is not None
        assert claims.user_id == uid
        assert claims.token_version == 3
        assert abs((claims.expires_at - expires).total_seconds()) < 1

    def test_rejects_wrong_secret(self) -> None:
        settings = get_settings()
        token, _ = create_access_token(settings, uuid.uuid4(), 0)
        other = settings.model_copy(update={"jwt_secret": "x" * 40})
        assert decode_access_token(other, token) is None

    def test_rejects_expired(self) -> None:
        settings = get_settings()
        payload = {"sub": str(uuid.uuid4()), "ver": 0, "iat": 0, "exp": 1, "typ": "access"}
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        assert decode_access_token(settings, token) is None

    def test_rejects_alg_none(self) -> None:
        settings = get_settings()
        payload = {"sub": str(uuid.uuid4()), "ver": 0, "iat": 0, "exp": 9999999999, "typ": "access"}
        token = jwt.encode(payload, key=None, algorithm="none")
        assert decode_access_token(settings, token) is None


class TestSettings:
    def test_rejects_placeholder_secret(self) -> None:
        with pytest.raises(ValueError, match="placeholder"):
            Settings(jwt_secret="CHANGE_ME_TO_A_LONG_RANDOM_STRING")  # type: ignore[call-arg]

    def test_rejects_short_secret(self) -> None:
        with pytest.raises(ValueError):
            Settings(jwt_secret="short")  # type: ignore[call-arg]

    def test_csv_origins(self) -> None:
        s = Settings(jwt_secret="y" * 40, cors_origins="http://a:1, http://b:2")  # type: ignore[call-arg,arg-type]
        assert s.cors_origins == ["http://a:1", "http://b:2"]

    def test_list_settings_from_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, http://127.0.0.1:3000")
        monkeypatch.setenv("ALLOWED_HOSTS", '["localhost", "api"]')
        s = Settings()  # type: ignore[call-arg]
        assert s.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
        assert s.allowed_hosts == ["localhost", "api"]


class TestRedaction:
    def test_redacts_key_patterns(self) -> None:
        assert "sk-abc" not in redact("key=sk-abcdefghijklmnopqrstuvwxyz")

    def test_json_formatter_redacts_sensitive_extras(self) -> None:
        record = logging.makeLogRecord(
            {"msg": "calling provider", "levelno": 20, "levelname": "INFO", "api_key": "secret123"}
        )
        out = JsonFormatter().format(record)
        assert "secret123" not in out
        assert "[REDACTED]" in out


def test_rate_limiter_window() -> None:
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=timedelta(minutes=1).total_seconds())
    assert limiter.hit("k")
    assert limiter.hit("k")
    assert not limiter.hit("k")
    assert limiter.hit("other")
    limiter.reset("k")
    assert limiter.hit("k")
