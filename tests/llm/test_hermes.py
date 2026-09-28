"""Тесты Hermes-моста: подпись V2, payload, выбор провайдера. Без сети."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import urllib.error

import pytest

from d2intel.llm import analyst, hermes


def _evidence() -> dict:
    return {
        "match_id": 659245,
        "league": "probe",
        "series_type": 2,
        "radiant": {"name": "A", "known": False},
        "dire": {"name": "B", "known": False},
        "h2h": {"games": 0},
    }


# ── подпись V2 ─────────────────────────────────────────────────────────────


def test_sign_is_hmac_of_timestamp_plus_body() -> None:
    ts, body, secret = "1700000000", b'{"a":1}', "s3cret"
    expected = hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).hexdigest()
    assert hermes.sign(ts, body, secret) == expected
    assert len(hermes.sign(ts, body, secret)) == 64


def test_sign_order_matters() -> None:
    """Подпись именно ts+body, а не body+ts — иначе мост вернёт 401."""
    ts, body, secret = "1700000000", b'{"a":1}', "s3cret"
    assert hermes.sign(ts, body, secret) != hmac.new(
        secret.encode(), body + ts.encode(), hashlib.sha256
    ).hexdigest()


def test_sign_changes_with_timestamp_and_body() -> None:
    assert hermes.sign("1", b"{}", "k") != hermes.sign("2", b"{}", "k")
    assert hermes.sign("1", b'{"a":1}', "k") != hermes.sign("1", b'{"a":2}', "k")


# ── payload ────────────────────────────────────────────────────────────────


def test_build_payload_shape() -> None:
    ev = _evidence()
    msgs = [{"role": "user", "content": "hi"}]
    out = hermes.build_payload(ev, msgs, "llm-analyst-v1")
    assert out["task"] == "analyze_match"
    assert out["expect_reply"] is True
    assert out["input"]["match_id"] == 659245
    assert out["input"]["messages"] == msgs
    assert out["input"]["evidence"] == ev
    assert out["input"]["prompt_version"] == "llm-analyst-v1"
    json.dumps(out, ensure_ascii=False)  # сериализуем без потерь


# ── post_to_bridge без сети ────────────────────────────────────────────────


def test_post_without_secret_does_not_touch_network(monkeypatch) -> None:
    monkeypatch.delenv("HERMES_BRIDGE_SECRET", raising=False)
    out = hermes.post_to_bridge({"task": "x"})
    assert out["ok"] is False
    assert "HERMES_BRIDGE_SECRET" in out["reason"]


class _FakeResp:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


def test_post_202_accepted_returns_pending(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_BRIDGE_SECRET", "k")
    captured: dict = {}

    def fake_urlopen(req, timeout=60):
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data
        return _FakeResp(202, '{"status": "accepted", "delivery_id": "abc"}')

    monkeypatch.setattr(hermes.urllib.request, "urlopen", fake_urlopen)
    out = hermes.post_to_bridge({"task": "analyze_match"})
    assert out["ok"] is True
    assert out["pending"] is True
    assert out["delivery_id"] == "abc"
    # подпись посчитана от ts + ровно тех байтов, что ушли
    lowered = {k.lower(): v for k, v in captured["headers"].items()}
    ts = lowered["x-webhook-timestamp"]
    assert lowered["x-webhook-signature-v2"] == hermes.sign(ts, captured["data"], "k")


def test_post_401_invalid_signature(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_BRIDGE_SECRET", "wrong")
    fp = io.BytesIO(b"Invalid signature")

    def fake_urlopen(req, timeout=60):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, fp)

    monkeypatch.setattr(hermes.urllib.request, "urlopen", fake_urlopen)
    out = hermes.post_to_bridge({"task": "x"})
    assert out["ok"] is False
    assert "401" in out["reason"]


# ── выбор провайдера в analyze ─────────────────────────────────────────────


def test_resolve_provider_defaults_to_atria(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert analyst.resolve_provider() == "atria"
    assert analyst.resolve_provider("hermes") == "hermes"
    monkeypatch.setenv("LLM_PROVIDER", "hermes")
    assert analyst.resolve_provider() == "hermes"


def test_analyze_default_still_calls_atria(monkeypatch) -> None:
    """Прямой вызов Atria без флага не меняется."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    called = {}

    def fake_call(messages):
        called["n"] = len(messages)
        return {"choices": [{"message": {"content": '{"p_radiant": 0.6}'}}]}

    monkeypatch.setattr(analyst, "_call_llm", fake_call)
    out = analyst.analyze(_evidence())
    assert called["n"] == 2  # system + user, как раньше
    assert out["p_radiant"] == pytest.approx(0.6)


def test_analyze_hermes_does_not_call_atria(monkeypatch) -> None:
    def boom(messages):
        raise AssertionError("прямой Atria вызван в hermes-режиме")

    monkeypatch.setattr(analyst, "_call_llm", boom)
    monkeypatch.setattr(
        hermes,
        "post_to_bridge",
        lambda payload: {"ok": True, "provider": "hermes", "pending": True, "delivery_id": "d1"},
    )
    out = analyst.analyze(_evidence(), provider="hermes")
    assert out["pending"] is True
    assert out["delivery_id"] == "d1"
    assert out["prompt_version"] == analyst.PROMPT_VERSION
