from __future__ import annotations

import asyncio
from types import SimpleNamespace

from veyrasoul.gateway.admission import AdmissionGate, AdmissionPolicy


def secured_policy(**overrides) -> AdmissionPolicy:
    values = {
        "required": True,
        "secret": "s" * 32,
        "turnstile_site_key": "unit-test-site-key",
        "turnstile_secret": "unit-test-turnstile-secret",
        "allowed_origins": ("https://anima.veyralux.org",),
        "max_connections": 2,
        "max_connections_per_client": 1,
        "max_concurrent_turns": 1,
        "max_turns_per_client_per_minute": 2,
        "max_turns_global_per_minute": 3,
        "binary_bytes_per_second": 100,
        "binary_burst_bytes": 100,
        "control_events_per_second": 2,
        "control_burst_events": 2,
    }
    values.update(overrides)
    return AdmissionPolicy(**values)


def test_signed_admission_token_is_short_lived_and_tamper_evident() -> None:
    gate = AdmissionGate(secured_policy(token_ttl_seconds=60))
    token = gate.issue_token(now=1_000)

    assert gate.verify_token(token, now=1_059)
    assert not gate.verify_token(token, now=1_061)
    assert not gate.verify_token(f"{token}x", now=1_001)


def test_required_handshake_needs_exact_origin_and_cookie() -> None:
    gate = AdmissionGate(secured_policy())
    token = gate.issue_token()
    device_token = gate.issue_device_token()
    valid = SimpleNamespace(
        headers={"origin": "https://anima.veyralux.org"},
        cookies={
            AdmissionGate.COOKIE_NAME: token,
            AdmissionGate.DEVICE_COOKIE_NAME: device_token,
        },
        client=SimpleNamespace(host="127.0.0.1"),
    )

    assert gate.validate_handshake(valid) is None
    valid.headers["origin"] = "https://evil.example"
    assert gate.validate_handshake(valid).code == "origin_denied"
    valid.headers["origin"] = "https://anima.veyralux.org"
    valid.cookies.pop(AdmissionGate.COOKIE_NAME)
    failure = gate.validate_handshake(valid)
    assert failure.code == "admission_required"
    assert failure.close_code == 4401


def test_connection_turn_and_media_budgets_are_bounded() -> None:
    async def scenario() -> None:
        gate = AdmissionGate(secured_policy())
        first, failure = await gate.try_connect("198.51.100.10")
        assert first is not None and failure is None
        duplicate, failure = await gate.try_connect("198.51.100.10")
        assert duplicate is None and failure.code == "connection_limited"
        second, failure = await gate.try_connect("198.51.100.11")
        assert second is not None and failure is None
        full, failure = await gate.try_connect("198.51.100.12")
        assert full is None and failure.code == "server_busy"

        assert first.budget.accept_binary(100, now=10.0)
        assert not first.budget.accept_binary(1, now=10.0)
        assert first.budget.accept_binary(50, now=10.5)
        assert first.budget.accept_control(now=20.0)
        assert first.budget.accept_control(now=20.0)
        assert not first.budget.accept_control(now=20.0)
        assert first.budget.accept_control(now=20.5)

        turn, failure = await gate.try_turn(first, now=20.0)
        assert turn is not None and failure is None
        busy, failure = await gate.try_turn(second, now=20.0)
        assert busy is None and failure.code == "server_busy"
        await turn.release()
        turn, failure = await gate.try_turn(first, now=21.0)
        assert turn is not None and failure is None
        await turn.release()
        limited, failure = await gate.try_turn(first, now=22.0)
        assert limited is None and failure.code == "turn_rate_limited"

        await first.release()
        await second.release()
        replacement, failure = await gate.try_connect("198.51.100.10")
        assert replacement is not None and failure is None
        await replacement.release()

    asyncio.run(scenario())


def test_expired_high_cardinality_turn_buckets_are_reclaimed() -> None:
    async def scenario() -> None:
        gate = AdmissionGate(
            secured_policy(
                max_turns_global_per_minute=1_000,
                max_concurrent_turns=1,
            )
        )
        for index in range(10):
            connection, _ = await gate.try_connect(f"198.51.100.{index}")
            assert connection is not None
            turn, failure = await gate.try_turn(connection, now=0.0)
            assert turn is not None and failure is None
            await turn.release()
            await connection.release()
        assert len(gate._turns_by_client) == 10

        connection, _ = await gate.try_connect("203.0.113.1")
        assert connection is not None
        turn, failure = await gate.try_turn(connection, now=61.0)
        assert turn is not None and failure is None
        assert len(gate._turns_by_client) == 1
        await turn.release()
        await connection.release()

    asyncio.run(scenario())
