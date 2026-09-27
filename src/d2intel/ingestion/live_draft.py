"""Live-драфт: OpenDota /api/live → ход драфта матча (ADR-008, фаза 2).

OpenDota /api/live отдаёт идущие игры; у игроков `hero_id` появляется в момент
пика, поэтому ход драфта виден в реальном времени. Имена команд на уровне
игры бывают NULL — матч ищется по `team_name` ИГРОКОВ (совпадение с парами
замороженных фикстур), а также по `league_id` (Wallachia = 20176).

Bans в /live отсутствуют — показываются только пики (10 героев). Hero names —
из кэша `artifacts/cache/opendota_heroes.json` (/api/constants/heroes).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

LIVE_URL = "https://api.opendota.com/api/live"
HEROES_URL = "https://api.opendota.com/api/constants/heroes"
USER_AGENT = "d2intel/0.1 (local research tool; contact: zetkaruss@gmail.com)"
CACHE_DIR = Path("artifacts/cache")


def fetch_live_games(client: httpx.Client | None = None) -> list[dict[str, Any]]:
    client = client or httpx.Client()
    response = client.get(LIVE_URL, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    return response.json()


def load_hero_names(cache_path: Path | None = None) -> dict[int, str]:
    path = cache_path or (CACHE_DIR / "opendota_heroes.json")
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return {int(k): v for k, v in data.items()}
    response = httpx.get(HEROES_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    raw = response.json()
    mapping = {int(k): v.get("localized_name") for k, v in raw.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return mapping


def _side_name(player: dict[str, Any]) -> str:
    team_name = (player.get("team_name") or "").strip()
    if team_name:
        return team_name
    return "Radiant" if player.get("team") == 0 else "Dire"


def find_live_game(
    games: list[dict[str, Any]],
    *,
    team_a: str,
    team_b: str,
    accounts_a: set[int] | None = None,
    accounts_b: set[int] | None = None,
) -> dict[str, Any] | None:
    """Найти нашу живую игру по пересечению account_id ИГРОКОВ.

    Имена команд уровня игры в /live бывают NULL, а фоллбек «по лиге» выдал
    бы чужой матч — единственный честный ключ: известные account_id игроков
    обеих команд (roster evidence из нашей БД). Порог: >=4 совпадений
    суммарно при наличии игроков обеих сторон.
    """
    accounts_a = accounts_a or set()
    accounts_b = accounts_b or set()
    best: tuple[int, dict[str, Any]] | None = None
    for game in games:
        ids = {p.get("account_id") for p in game.get("players", [])}
        overlap = len((ids & accounts_a) | (ids & accounts_b))
        both_sides = bool(ids & accounts_a) and bool(ids & accounts_b)
        if overlap >= 4 and both_sides and (best is None or overlap > best[0]):
            best = (overlap, game)
    return best[1] if best else None


def draft_progress(
    game: dict[str, Any], hero_names: dict[int, str]
) -> dict[str, Any]:
    """Ход драфта: пики по сторонам + счёт/время игры."""
    radiant: list[dict[str, Any]] = []
    dire: list[dict[str, Any]] = []
    for player in game.get("players", []):
        hero_id = player.get("hero_id")
        entry = {
            "player": player.get("player_name"),
            "account_id": player.get("account_id"),
            "hero_id": hero_id,
            "hero": hero_names.get(int(hero_id)) if hero_id else None,
        }
        if player.get("team") == 0:
            radiant.append(entry)
        else:
            dire.append(entry)
    return {
        "series_id": game.get("series_id"),
        "league_id": game.get("league_id"),
        "league_name": game.get("league_name"),
        "game_time_seconds": game.get("game_time"),
        "radiant_score": game.get("radiant_score"),
        "dire_score": game.get("dire_score"),
        "radiant_team": game.get("radiant_team_name"),
        "dire_team": game.get("dire_team_name"),
        "radiant_picks": radiant,
        "dire_picks": dire,
        "picks_count": len(radiant) + len(dire),
        "note": "Bans в /api/live отсутствуют; hero_id появляется в момент пика",
    }


def live_match_view(
    *,
    team_a: str,
    team_b: str,
    accounts_a: set[int] | None = None,
    accounts_b: set[int] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Полный live-вид матча для UI: команды, счёт убийств, пики по сторонам."""
    games = fetch_live_games(client)
    game = find_live_game(
        games, team_a=team_a, team_b=team_b,
        accounts_a=accounts_a, accounts_b=accounts_b,
    )
    hero_names = load_hero_names()
    result: dict[str, Any] = {
        "searching_for": f"{team_a} vs {team_b}",
        "live_games_scanned": len(games),
        "found": False,
    }
    if game is None:
        result["message"] = (
            "Наша пара пока не опознана в live-фиде OpenDota: матч попадает "
            "в фид через несколько минут после старта, имена команд уровня "
            "игры бывают пусты — опознаём строго по account_id игроков из "
            "нашей БД (чужой драфт той же лиги не показываем)."
        )
        return result

    radiant_players, dire_players = [], []
    for player in game.get("players", []):
        hero_id = player.get("hero_id")
        entry = {
            "name": player.get("name") or "—",
            "hero": hero_names.get(int(hero_id)) if hero_id else None,
            "team_tag": player.get("team_tag"),
        }
        if player.get("team") == 0:
            radiant_players.append(entry)
        else:
            dire_players.append(entry)
    return {
        "found": True,
        "series_id": game.get("series_id"),
        "game_time_seconds": game.get("game_time"),
        "radiant": {
            "name": game.get("team_name_radiant") or "Radiant",
            "kills": game.get("radiant_score"),
            "players": radiant_players,
        },
        "dire": {
            "name": game.get("team_name_dire") or "Dire",
            "kills": game.get("dire_score"),
            "players": dire_players,
        },
        "note": "KDA/items/bans в /api/live отсутствуют (глубина платных фидов); полный драфт с банами — в карточке после каждой доигранной карты",
    }
