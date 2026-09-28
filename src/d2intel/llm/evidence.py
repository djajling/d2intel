"""Сбор pre-match evidence из публичного OpenDota API.

Всё, что отдаёт этот модуль, известно ДО начала целевого матча: форма команд
и personal только по строго более ранним встречам. Любая пост-матч статистика
(финальный счёт, GPM, драфт целиком) сюда не попадает — эксперимент честный.

Источники: /proMatches (пагинация по less_than_match_id), /teams/{id}/matches,
/constants/heroes. Без ключа, без скрапинга.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

OPENODTA_BASE = "https://api.opendota.com/api"
TIMEOUT = 60
#: Горизонт формы: 30 дней до матча.
FORM_WINDOW_DAYS = 30
#: Сколько матчей команды тянуть из её истории.
TEAM_HISTORY_LIMIT = 40


class EvidenceError(RuntimeError):
    """Сбой сбора evidence — эксперимент не может продолжаться."""


def api_get(path: str, cache: dict[str, Any], cache_key: str | None = None) -> Any:
    """GET к OpenDota с кэшем по ключу вызова."""
    key = cache_key or path
    if key in cache:
        return cache[key]
    url = OPENODTA_BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": "d2intel-experiment/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise EvidenceError(f"OpenDota HTTP {exc.code} на {path}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EvidenceError(f"OpenDota недоступен: {path}: {exc}") from exc
    cache[key] = data
    return data


def fetch_corpus(pages: int, cache: dict[str, Any]) -> list[dict]:
    """Пул про-матчей для оценки формы команд.

    Пагинация: каждый следующий запрос отдаёт матчи строго левее по времени.
    """
    corpus: list[dict] = []
    cursor: int | None = None
    for _ in range(pages):
        path = "/proMatches"
        if cursor is not None:
            path += f"?less_than_match_id={cursor}"
        batch = api_get(path, cache)
        if not batch:
            break
        corpus.extend(batch)
        oldest = min(b["match_id"] for b in batch)
        if oldest == cursor:
            break
        cursor = oldest
        time.sleep(0.5)
    # дедуп: пагинация может пересекаться на границах
    seen: set[int] = set()
    uniq: list[dict] = []
    for m in corpus:
        if m["match_id"] in seen:
            continue
        seen.add(m["match_id"])
        uniq.append(m)
    return uniq


def team_form(
    corpus: list[dict],
    team_name: str,
    cutoff_ts: int,
    cache: dict[str, Any],
) -> dict:
    """Форма команды на момент cutoff: только строго более ранние матчи.

    Сначала по корпусу, потом добираем историю команды напрямую — так форма
    есть даже для команд, которых нет в текущей ленте.
    """
    own = [
        m
        for m in corpus
        if cutoff_ts - m["start_time"] > 0
        and (m.get("radiant_name") == team_name or m.get("dire_name") == team_name)
    ]
    own.sort(key=lambda m: -m["start_time"])
    if len(own) < 5:
        team_id = _team_id(team_name, cache)
        if team_id is not None:
            hist = api_get(f"/teams/{team_id}/matches", cache, f"team:{team_id}:matches")
            for m in hist:
                if m.get("start_time", 0) >= cutoff_ts:
                    continue
                m.setdefault("league_name", m.get("league_name") or "?")
                own.append(m)
            own.sort(key=lambda m: -m["start_time"])
    own = own[:TEAM_HISTORY_LIMIT]
    if not own:
        return {
            "name": team_name,
            "known": False,
            "games": 0,
            "note": "нет истории в OpenDota",
        }
    wins = 0
    for m in own:
        is_radiant = m.get("radiant_name") == team_name
        won = bool(m.get("radiant_win")) if is_radiant else not bool(m.get("radiant_win"))
        if won:
            wins += 1
    return {
        "name": team_name,
        "known": True,
        "games": len(own),
        "wins": wins,
        "winrate": round(wins / len(own), 3),
        "last_game": datetime.fromtimestamp(own[0]["start_time"], tz=UTC).strftime("%Y-%m-%d"),
        "leagues": sorted({m.get("league_name") or "?" for m in own[:10]}),
    }


def _team_id(team_name: str, cache: dict[str, Any]) -> int | None:
    """Поиск team_id по имени через /teams. Кэшируется."""
    key = f"teamid:{team_name}"
    if key in cache:
        return cache[key]
    teams = api_get("/teams", cache, "teams:all")
    for t in teams:
        if (t.get("name") or "").lower() == team_name.lower() or (t.get("tag") or "").lower() == team_name.lower():
            cache[key] = t["team_id"]
            return t["team_id"]
    cache[key] = None
    return None


def head_to_head(corpus: list[dict], a: str, b: str, cutoff_ts: int) -> dict:
    """Личные встречи до cutoff — самый сильный pre-match сигнал."""
    games = [
        m
        for m in corpus
        if cutoff_ts - m["start_time"] > 0
        and {m.get("radiant_name"), m.get("dire_name")} == {a, b}
    ]
    if not games:
        return {"games": 0, "note": "личных встреч не найдено"}
    a_wins = 0
    for m in games:
        if (m.get("radiant_win") and m.get("radiant_name") == a) or (
            not m.get("radiant_win") and m.get("dire_name") == a
        ):
            a_wins += 1
    return {
        "games": len(games),
        f"{a}_wins": a_wins,
        f"{b}_wins": len(games) - a_wins,
        "last": datetime.fromtimestamp(max(g["start_time"] for g in games), tz=UTC).strftime("%Y-%m-%d"),
    }


def build_evidence(
    target: dict,
    corpus: list[dict],
    cache: dict[str, Any],
) -> dict:
    """Полный pre-match контекст по целевому матчу."""
    cutoff = int(target["start_time"])
    radiant = target.get("radiant_name") or "Radiant"
    dire = target.get("dire_name") or "Dire"
    return {
        "match_id": target["match_id"],
        "start_time": datetime.fromtimestamp(cutoff, tz=UTC).isoformat(),
        "league": target.get("league_name"),
        "series_type": target.get("series_type"),
        "patch": target.get("patch"),
        "radiant": team_form(corpus, radiant, cutoff, cache),
        "dire": team_form(corpus, dire, cutoff, cache),
        "h2h": head_to_head(corpus, radiant, dire, cutoff),
    }

# BLAST Slam VIII filter (updated 2026-09-28): tournament filter is "blast".
# Format-aware prediction weights: Bo1 (group) -> high form+H2H impact;
# Bo3/Bo5 (playoff) -> consistency + series endurance weighted more.
# Page source: liquipedia.net/dota2/BLAST/SLAM/8 (under construction at time of update).
# Matches appear in OpenDota when live; pre-event only schedule evidence.
