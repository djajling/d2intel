"""STRATZ live-драфт — тесты без сетевых запросов (ADR-008, фаза 2).

Фиксируют то, что чинило запрос400 и что защищает квоту free-tier:

* в запросе только алиасы, подтверждённые интроспекцией MatchLivePlayerType
  (`playerSlot`/`isRadiant`); старые `slot`/`team` =400;
* пики и баны берутся из playbackData.pickBans (подтверждено интроспекцией
  MatchLivePlaybackDataType/MatchLivePickBanType 2026-09-27);
* тело ошибки не теряется (раньше его съедал raise_for_status);
* троттлинг квоты: второй запрос в окне не уходит в сеть вообще;
* опознание «нашей» игры идёт по steamAccountId игроков, а не по названиям
  команд; имена сторон подставляются с учётом стороны Radiant/Dire.

Сеть: нет. Ключ: подменяется через monkeypatch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from d2intel.api import schedule
from d2intel.app import create_app
from d2intel.db import get_db
from d2intel.ingestion.live_draft import load_hero_names


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text or payload is None else json.dumps(payload)

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise json.JSONDecodeError("Expecting value", self.text, 0)
        return self._payload


class _FakeClient:
    """Принимает готовые ответы; фактические URL/заголовки пишет в calls."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, json: Any = None, headers: Any = None, timeout: Any = None) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise AssertionError("лишний сетевой вызов STRATZ")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _stratz_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STRATZ_API_KEY", "test-key")
    # Своё состояние квоты на тест: реальный файл artifacts/cache прогон не
    # обнуляет, иначе после каждого pytest сторож квоты слепнет.
    monkeypatch.setattr(schedule, "STRATZ_STATE_PATH", tmp_path / "stratz_quota.json")
    schedule._stratz_reset_state()
    yield
    schedule._stratz_reset_state()


def _match(players: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    base = {
        "matchId": 99887766,
        "gameTime": 420,
        "radiantScore": 7,
        "direScore": 3,
        "players": players,
    }
    base.update(overrides)
    return base


def _squad(ids: range, radiant: bool) -> list[dict[str, Any]]:
    return [
        {
            "steamAccountId": i,
            "heroId": 1 if radiant else 2,
            "isRadiant": radiant,
            "playerSlot": 0 if radiant else 128,
            "name": f"player_{i}",
        }
        for i in ids
    ]


def test_live_query_uses_confirmed_schema_aliases() -> None:
    query = schedule.STRATZ_LIVE_QUERY
    for alias in ("playerSlot", "isRadiant", "steamAccountId", "heroId", "matchId"):
        assert alias in query, alias
    # Старые имена полей отсутствуют — именно они давали400.
    assert not re.search(r"\bslot\b", query)
    assert not re.search(r"\bteam\b", query)


def test_graphql_error_body_is_surfaced() -> None:
    """Тело ответа с `errors` не должно теряться — на нём видна причина отказа."""
    client = _FakeClient(
        [
            _FakeResponse(
                200,
                {
                    "errors": [
                        {"message": 'Cannot query field "slot" on type "MatchLivePlayerType".'}
                    ]
                },
            )
        ]
    )
    with pytest.raises(ValueError) as excinfo:
        schedule._stratz_live_matches(client=client)
    assert "Cannot query field" in str(excinfo.value)


def test_non_200_body_is_included() -> None:
    client = _FakeClient([_FakeResponse(400, text="schema validation failed")])
    with pytest.raises(ValueError) as excinfo:
        schedule._stratz_live_matches(client=client)
    assert "HTTP 400" in str(excinfo.value)
    assert "schema validation failed" in str(excinfo.value)


def test_quota_throttle_blocks_second_request() -> None:
    """Второй запрос в окне не уходит в сеть: квота free-tier ~2/15 мин."""
    client = _FakeClient([_FakeResponse(200, {"data": {"live": {"matches": []}}})])
    assert schedule._stratz_live_matches(client=client) == []
    with pytest.raises(schedule._StratzThrottled):
        schedule._stratz_live_matches(client=client)
    assert len(client.calls) == 1


def test_rate_limit_arms_cooldown() -> None:
    """403 → пауза на 15 минут, до её окончания в сеть не ходим."""
    client = _FakeClient([_FakeResponse(403, text="You cannot use more than 2 IP Addresses")])
    with pytest.raises(ValueError) as excinfo:
        schedule._stratz_live_matches(client=client)
    assert "rate-limit" in str(excinfo.value)
    assert schedule._STRATZ_STATE["cooldown_until"] > 0
    with pytest.raises(schedule._StratzThrottled):
        schedule._stratz_live_matches(client=client)
    assert len(client.calls) == 1


def test_quota_state_survives_process_restart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Квота — внешний ресурс: после рестарта процесса сторож не слепнет.

    Сервер перезапускают часто (перезалив кода). Пока состояние жило только в
    памяти, новый процесс считал, что не делал запросов, и тратил слот.
    """
    state_path = tmp_path / "quota.json"
    monkeypatch.setattr(schedule, "STRATZ_STATE_PATH", state_path)
    schedule._stratz_reset_state()
    client = _FakeClient([_FakeResponse(200, {"data": {"live": {"matches": []}}})])
    assert schedule._stratz_live_matches(client=client) == []
    assert state_path.exists(), "состояние квоты должно быть записано на диск"

    # «Рестарт»: память процесса пустая, файл остался.
    schedule._STRATZ_STATE["last_attempt_at"] = 0.0
    schedule._STRATZ_STATE["cooldown_until"] = 0.0
    schedule._stratz_load_state()
    with pytest.raises(schedule._StratzThrottled):
        schedule._stratz_live_matches(client=_FakeClient([]))


def test_corrupt_quota_file_does_not_block_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Битый файл состояния — не причина молча отключать источник."""
    state_path = tmp_path / "quota.json"
    state_path.write_text("{не json", encoding="utf-8")
    monkeypatch.setattr(schedule, "STRATZ_STATE_PATH", state_path)
    schedule._stratz_reset_state()
    schedule._stratz_load_state()
    client = _FakeClient([_FakeResponse(200, {"data": {"live": {"matches": []}}})])
    assert schedule._stratz_live_matches(client=client) == []
    assert len(client.calls) == 1


def test_pick_identifies_match_by_accounts_not_team_names() -> None:
    match = _match(_squad(range(1, 6), radiant=True) + _squad(range(6, 11), radiant=False))
    client = _FakeClient([_FakeResponse(200, {"data": {"live": {"matches": [match]}}})])
    picked = schedule._stratz_pick_live_match(
        accounts_a={1, 2, 3, 4, 5},
        accounts_b={6, 7, 8, 9, 10},
        label_a="Natus Vincere",
        label_b="Aurora Gaming",
        client=client,
    )
    assert picked is not None
    found, radiant_label, dire_label = picked
    assert found["matchId"] == 99887766
    # Сторона опознана по isRadiant наших игроков, а не по имени команды.
    assert radiant_label == "Natus Vincere"
    assert dire_label == "Aurora Gaming"


def test_pick_swaps_labels_when_team_is_on_dire() -> None:
    match = _match(_squad(range(6, 11), radiant=True) + _squad(range(1, 6), radiant=False))
    client = _FakeClient([_FakeResponse(200, {"data": {"live": {"matches": [match]}}})])
    picked = schedule._stratz_pick_live_match(
        accounts_a={1, 2, 3, 4, 5},
        accounts_b={6, 7, 8, 9, 10},
        label_a="Natus Vincere",
        label_b="Aurora Gaming",
        client=client,
    )
    assert picked is not None
    _, radiant_label, dire_label = picked
    assert radiant_label == "Aurora Gaming"
    assert dire_label == "Natus Vincere"


def test_pick_requires_both_sides_and_threshold() -> None:
    """Порог как в OpenDota-пути: >=4 совпадений и обе стороны представлены."""
    only_one_side = _match(_squad(range(1, 6), radiant=True))
    client = _FakeClient([_FakeResponse(200, {"data": {"live": {"matches": [only_one_side]}}})])
    assert (
        schedule._stratz_pick_live_match(
            accounts_a={1, 2, 3, 4, 5},
            accounts_b={6, 7, 8, 9, 10},
            label_a="A",
            label_b="B",
            client=client,
        )
        is None
    )

    three_overlap = _match(
        _squad(range(1, 3), radiant=True) + _squad(range(6, 7), radiant=False)
    )
    schedule._stratz_reset_state()  # второй запрос того же теста — иначе троттлинг
    client = _FakeClient([_FakeResponse(200, {"data": {"live": {"matches": [three_overlap]}}})])
    assert (
        schedule._stratz_pick_live_match(
            accounts_a={1, 2, 3},
            accounts_b={6, 7, 8, 9, 10},
            label_a="A",
            label_b="B",
            client=client,
        )
        is None
    )


def test_pick_does_not_match_by_team_name_alone() -> None:
    """Игра с посторонними командами не подхватывается, даже если названия совпали."""
    stranger = _match(
        _squad(range(100, 105), radiant=True) + _squad(range(200, 205), radiant=False)
    )
    stranger["players"][0]["name"] = "Natus Vincere"
    client = _FakeClient([_FakeResponse(200, {"data": {"live": {"matches": [stranger]}}})])
    assert (
        schedule._stratz_pick_live_match(
            accounts_a={1, 2, 3, 4, 5},
            accounts_b={6, 7, 8, 9, 10},
            label_a="Natus Vincere",
            label_b="Aurora Gaming",
            client=client,
        )
        is None
    )


@pytest.fixture
def api(db_session) -> TestClient:  # noqa: ANN001
    app = create_app()

    def _override() -> Any:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_live_draft_endpoint_returns_stratz_view_without_series_id(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ответ UI: source=stratz, никнеймы игроков, series_id НЕ подменяется
    чужим matchId (иначе подписан указал бы на наш series_key из OpenDota)."""
    client = api
    created = client.post(
        "/api/schedule",
        json={
            "tournament_label": "PGL Wallachia S9",
            "team_a_label": "Natus Vincere",
            "team_b_label": "Aurora Gaming",
            "scheduled_at": "2026-09-28T15:00:00+03:00",
        },
    )
    assert created.status_code == 201, created.text
    fixture_id = created.json()["id"]

    class _Completed:
        returncode = 0
        stdout = "frozen 0f2e1111-2222-3333-4444-555555555555\n"
        stderr = ""

    monkeypatch.setattr(
        "d2intel.api.schedule.subprocess.run", lambda *a, **k: _Completed()
    )
    assert client.post(f"/api/schedule/{fixture_id}/freeze").status_code == 200

    match = _match(_squad(range(1, 6), radiant=True) + _squad(range(6, 11), radiant=False))

    def _fake_pick(**kwargs: Any) -> tuple[dict[str, Any], str, str]:
        return match, "Natus Vincere", "Aurora Gaming"

    monkeypatch.setattr(schedule, "_stratz_pick_live_match", _fake_pick)

    body = client.get("/api/schedule/live-draft").json()
    assert body["found"] is True
    assert body["source"] == "stratz"
    assert body["stratz_match_id"] == 99887766
    assert body["series_id"] is None
    assert body["radiant"]["name"] == "Natus Vincere"
    assert body["radiant"]["kills"] == 7
    assert body["dire"]["name"] == "Aurora Gaming"
    players = body["radiant"]["players"] + body["dire"]["players"]
    assert len(players) == 10
    assert all(p["name"].startswith("player_") for p in players)
    assert all("hero" in p for p in players)
    assert "playbackData.pickBans" in body["note"]
    # playbackData в фейке отсутствует — честные пустые списки, не нули.
    assert body["bans"] == {"radiant": [], "dire": []}
    assert body["picks_by_order"] == {"radiant": [], "dire": []}


def test_live_draft_stratz_extracts_bans_and_picks_in_order(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Баны и пики из playbackData.pickBans попадают в ответ; сортировка по
    order; бан = isPick=false + bannedHeroId, пик = isPick=true + heroId."""
    client = api
    created = client.post(
        "/api/schedule",
        json={
            "tournament_label": "PGL Wallachia S9",
            "team_a_label": "Natus Vincere",
            "team_b_label": "Aurora Gaming",
            "scheduled_at": "2026-09-28T15:00:00+03:00",
        },
    )
    assert created.status_code == 201, created.text
    fixture_id = created.json()["id"]

    class _Completed:
        returncode = 0
        stdout = "frozen 0f2e1111-2222-3333-4444-555555555555\n"
        stderr = ""

    monkeypatch.setattr(
        "d2intel.api.schedule.subprocess.run", lambda *a, **k: _Completed()
    )
    assert client.post(f"/api/schedule/{fixture_id}/freeze").status_code == 200

    match = _match(
        _squad(range(1, 6), radiant=True) + _squad(range(6, 11), radiant=False),
        playbackData={
            "pickBans": [
                {"isPick": False, "bannedHeroId": 30, "isRadiant": True, "order": 0},
                {"isPick": False, "bannedHeroId": 45, "isRadiant": False, "order": 1},
                {"isPick": True, "heroId": 8, "isRadiant": True, "order": 10},
                {"isPick": True, "heroId": 5, "isRadiant": False, "order": 11},
                {"isPick": True, "heroId": 35, "isRadiant": True, "order": 12},
                {"isPick": True, "heroId": 41, "isRadiant": False, "order": 13},
            ]
        },
    )

    def _fake_pick(**kwargs: Any) -> tuple[dict[str, Any], str, str]:
        return match, "Natus Vincere", "Aurora Gaming"

    monkeypatch.setattr(schedule, "_stratz_pick_live_match", _fake_pick)

    body = client.get("/api/schedule/live-draft").json()
    assert body["source"] == "stratz"
    # Порядок ходов сохранён (order), стороны не перепутаны.
    assert body["picks_by_order"] == {
        "radiant": [8, 35],
        "dire": [5, 41],
    }
    assert [b["hero"] for b in body["bans"]["radiant"]] == [load_hero_names().get(30)]
    assert [b["order"] for b in body["bans"]["radiant"]] == [0]
    assert [b["hero"] for b in body["bans"]["dire"]] == [
        load_hero_names().get(45)
    ]
    assert "playbackData.pickBans" in body["note"]
