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
    league_id: int | None = None,
) -> dict[str, Any] | None:
    """Найти живую игру по team_name игроков; fallback — league_id.

    Совпадение: в одной игре встречаются игроки обеих команд (по подстроке,
    без регистра). Названия команд уровня игры в /live часто NULL.
    """
    a, b = team_a.strip().lower(), team_b.strip().lower()
    # Только точное совпадение по team_name ИГРОКОВ обеих команд.
    # Фоллбек по league_id запрещён: лига может идти параллельно в нескольких
    # играх — выдать чужой драфт за наш было бы подменой (честность ADR-008).
    for game in games:
        players = game.get("players", [])
        names = [_side_name(p).lower() for p in players]
        has_a = any(a in name or name in a for name in names if name)
        has_b = any(b in name or name in b for name in names if name)
        if has_a and has_b:
            return game
    return None



# --------------------------------------------------------------------------- #
# STRATZ (платный лимит free-tier): live с пиками и банами — по ключу владельца
# ---------------------------------------------------------------------------

STRATZ_GRAPHQL = "https://api.stratz.com/graphql"


def _stratz_key() -> str | None:
    """Ключ STRATZ из .env корня репозитория (в git не попадает)."""
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("STRATZ_API_KEY="):
            return line.split("=", 1)[1].strip() or None
    return None


def stratz_live_match(
    *,
    team_a: str,
    team_b: str,
    client: httpx.Client | None = None,
) -> dict[str, Any] | None:
    """Живой матч STRATZ с пиками и банами, если игра найдена.

    Ограничения free-tier жёсткие (проба 2026-09-27: блок по IP до 15 минут) —
    вызывать НЕ чаще раза в минуту и только когда игра реально идёт.
    """
    key = _stratz_key()
    if key is None:
        return None
    client = client or httpx.Client()
    query = {
        "query": (
            "{ live { matches { matchId gameState gameTime "
            "league { id displayName } "
            "radiantTeam { name } direTeam { name } "
            "players { heroId slot team } } } }"
        )
    }
    response = client.post(
        STRATZ_GRAPHQL,
        json=query,
        headers={
            "Authorization": f"Bearer {key}",
            "User-Agent": "STRATZ_API",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if response.status_code == 403:
        raise ValueError(f"STRATZ rate limit: {response.text[:150]}")
    response.raise_for_status()
    matches = response.json()["data"]["live"]["matches"]
    a, b = team_a.strip().lower(), team_b.strip().lower()
    for match in matches:
        ra = ((match.get("radiantTeam") or {}).get("name") or "").lower()
        di = ((match.get("direTeam") or {}).get("name") or "").lower()
        if (a in ra or ra in a) and (b in di or di in b):
            return match
        if (a in di or di in a) and (b in ra or ra in b):
            return match
    return None
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


def live_draft_for(
    *,
    team_a: str,
    team_b: str,
    league_id: int | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Полный ответ для UI: нашли игру или честно «ещё не появилась»."""
    games = fetch_live_games(client)
    game = find_live_game(games, team_a=team_a, team_b=team_b, league_id=league_id)
    hero_names = load_hero_names()
    result: dict[str, Any] = {
        "searching_for": f"{team_a} vs {team_b}",
        "live_games_scanned": len(games),
        "found": False,
    }
    if game is None:
        league_games = (
            [g for g in games if g.get("league_id") == league_id]
            if league_id is not None
            else []
        )
        result["message"] = (
            "Наша пара пока не опознана в live-фиде OpenDota (фид добавляет "
            "игры с задержкой, имена команд уровня игры бывают пусты). "
            + (
                f"В лиге сейчас идут {len(league_games)} игр(ы), но опознать "
                "наши команды в них нельзя — показывать чужой драфт не будем."
                if league_games
                else "Опрос продолжается."
            )
        )
        return result
    progress = draft_progress(game, hero_names)
    result.update({"found": True, **progress})
    return result
