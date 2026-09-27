"""Расписание турниров и матчей — ручной ввод владельца + freeze по фикстуре.

Легального автоматического источника расписаний не существует (вердикт
SRC-002), поэтому фикстуры вводятся владельцем вручную (турнир, команды,
время) и живут в `scheduled_match` (миграция 0004). Это операционный список
для prospective-контура, не evidence-данные.

Действия над фикстурой:

- `POST /api/schedule/{id}/freeze` — запускает проверенный CLI
  `scripts/prospective_freeze.py` (LR champion, cutoff = now, immutable
  файл в artifacts/prospective) и связывает freeze_id с фикстурой. Ошибки
  резолва команд/модели возвращаются честно, статус не меняется.
- `POST /api/schedule/{id}/draft` — сохраняет НАБЛЮДАЕМЫЙ драфт (введён
  владельцем с трансляции) как данные для Gate-2 (ADR-006). Текущая модель
  драфт-информированной НЕ является: поле — сбор данных, а не вход прогноза,
  что явно отражено в ответе.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.db import get_db
from d2intel.ingestion.liquipedia_schedule import (
    refresh_matches_portal,
    refresh_schedule,
)
from d2intel.ingestion.live_draft import live_draft_for

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

REPO_ROOT = Path(__file__).resolve().parents[3]  # (уже определён ниже — оставить один)
DEFAULT_LIQUIPEDIA_PAGE = "PGL/Wallachia/9"
CACHE_DIR = Path("artifacts/cache")

REPO_ROOT = Path(__file__).resolve().parents[3]
FREEZE_SCRIPT = REPO_ROOT / "scripts" / "prospective_freeze.py"
FREEZE_TIMEOUT_SECONDS = 300

_SCHEDULE_SQL = """
    SELECT
        id, tournament_label, team_a_label, team_b_label, stage_label,
        scheduled_at, status, freeze_id, draft_observed, notes, created_at, updated_at
    FROM scheduled_match
"""

def notify_telegram(text: str) -> bool:
    """Push в Telegram владельца (ключ/чат в .env, в git не попадают)."""
    import os

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        env_path = REPO_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1].strip()
    if not token or not chat_id:
        return False
    try:
        import httpx as _httpx

        response = _httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": int(chat_id), "text": text},
            timeout=15,
        )
        return response.status_code == 200
    except Exception:  # noqa: BLE001 — push не должен ломать основной поток
        return False


_DRAFT_NOTE = (
    "Драфт сохранён как наблюдение для будущего Gate-2 (ADR-006): текущая "
    "модель драфт-информированной не является, прогноз от этого не меняется."
)


class ScheduleCreate(BaseModel):
    """Ручной ввод фикстуры владельцем."""

    tournament_label: str = Field(min_length=1, max_length=200)
    team_a_label: str = Field(min_length=1, max_length=100)
    team_b_label: str = Field(min_length=1, max_length=100)
    stage_label: str | None = Field(default=None, max_length=200)
    scheduled_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)


class DraftObservation(BaseModel):
    """Наблюдаемый драфт (evidence для Gate-2), структура свободная."""

    draft: dict[str, Any]


def _row_dict(row: Any) -> dict[str, Any]:
    data = dict(row._mapping)
    for key in ("scheduled_at", "created_at", "updated_at"):
        if data.get(key) is not None:
            data[key] = data[key].isoformat()
    return data


def _load_row(db: Session, fixture_id: str) -> dict[str, Any]:
    row = db.execute(
        text(_SCHEDULE_SQL + " WHERE id = CAST(:id AS uuid)"), {"id": fixture_id}
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фикстура не найдена")
    return _row_dict(row)


@router.get("")
def list_schedule(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict[str, Any]]:
    """Расписание: сначала предстоящие (по времени), затем остальные."""
    query = _SCHEDULE_SQL
    params: dict[str, Any] = {}
    if status_filter:
        query += " WHERE status = :status"
        params["status"] = status_filter
    query += " ORDER BY (status = 'upcoming') DESC, scheduled_at ASC NULLS LAST, created_at DESC"
    return [_row_dict(row) for row in db.execute(text(query), params).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_fixture(payload: ScheduleCreate, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Добавить фикстуру вручную (ручной ввод — единственный честный путь)."""
    if payload.team_a_label.strip().lower() == payload.team_b_label.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Команды должны различаться"
        )
    row = db.execute(
        text(
            """
            INSERT INTO scheduled_match
                (tournament_label, team_a_label, team_b_label, stage_label,
                 scheduled_at, notes)
            VALUES
                (:tournament, :team_a, :team_b, :stage, :scheduled_at, :notes)
            RETURNING id
            """
        ),
        {
            "tournament": payload.tournament_label.strip(),
            "team_a": payload.team_a_label.strip(),
            "team_b": payload.team_b_label.strip(),
            "stage": payload.stage_label,
            "scheduled_at": payload.scheduled_at,
            "notes": payload.notes,
        },
    ).scalar_one()
    db.commit()
    return _load_row(db, str(row))


@router.delete("/{fixture_id}")
def delete_fixture(fixture_id: str, db: Session = Depends(get_db)) -> dict[str, str]:  # noqa: B008
    """Удалить фикстуру (локальный операционный список, не evidence)."""
    deleted = db.execute(
        text(
            "DELETE FROM scheduled_match WHERE id = CAST(:id AS uuid) "
            "RETURNING id"
        ),
        {"id": fixture_id},
    ).first()
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фикстура не найдена")
    db.commit()
    return {"deleted": fixture_id}


@router.post("/{fixture_id}/freeze")
def freeze_fixture(fixture_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Заморозить prospective-прогноз по фикстуре (cutoff = now, immutable)."""
    fixture = _load_row(db, fixture_id)
    if fixture["status"] == "frozen":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Фикстура уже заморожена: freeze_id={fixture['freeze_id']}",
        )
    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(FREEZE_SCRIPT),
            "--team-a",
            str(fixture["team_a_label"]),
            "--team-b",
            str(fixture["team_b_label"]),
        ],
        capture_output=True,
        text=True,
        timeout=FREEZE_TIMEOUT_SECONDS,
        cwd=str(REPO_ROOT),
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Заморозка не удалась: "
                f"{(completed.stderr or completed.stdout).strip()[-400:]}"
            ),
        )
    freeze_id = _parse_freeze_id(completed.stdout)
    if freeze_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Заморозка отработала, но freeze_id не найден в выводе",
        )
    db.execute(
        text(
            "UPDATE scheduled_match SET status = 'frozen', freeze_id = :freeze_id, "
            "updated_at = now() WHERE id = CAST(:id AS uuid)"
        ),
        {"freeze_id": freeze_id, "id": fixture_id},
    )
    db.commit()
    updated = _load_row(db, fixture_id)
    updated["freeze_output"] = completed.stdout.strip()
    return updated


def _parse_freeze_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if line.startswith("frozen "):
            return line.split(maxsplit=1)[1].strip()
    return None


@router.get("/external")
def external_schedule(
    page: str = Query(default=DEFAULT_LIQUIPEDIA_PAGE, max_length=120),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Расписание с Liquipedia (ADR-008, display-only, кэш TTL + attribution)."""
    del db  # внешний источник, БД не используется
    slug = page.replace("/", "_")
    cache_path = CACHE_DIR / f"liquipedia_schedule_{slug}.json"
    try:
        data = refresh_schedule(
            page,
            cache_path,
            force=refresh,
            client=httpx.Client(),
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Liquipedia недоступен ({exc}). Ручное расписание продолжает "
                "работать — добавьте фикстуру вручную."
            ),
        ) from exc
    return data


@router.get("/external/matches")
def external_matches_portal(
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    """Матчи ВСЕХ турниров с портала Liquipedia:Matches (ADR-008)."""
    cache_path = CACHE_DIR / "liquipedia_matches_portal.json"
    try:
        data = refresh_matches_portal(
            cache_path,
            force=refresh,
            client=httpx.Client(),
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Liquipedia недоступен ({exc}). Ручное расписание работает.",
        ) from exc
    return data


@router.post("/auto-freeze")
def auto_freeze(db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Авто-заморозка (разрешение владельца 2026-09-27): портал → импорт → freeze.

    Идемпотентно и безопасно для повторных вызовов:
    1. Новые предстоящие матчи Wallachia с портала импортируются (без дублей
       по паре команд среди upcoming).
    2. Фикстуры, до старта которых осталось <= 10 минут, замораживаются
       (через тот же честный CLI; после старта — не замораживаются никогда).
    3. Фикстуры, чей старт прошёл без заморозки, помечаются `missed_start`
       вместо фальшивой заморозки.
    """
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    imported: list[dict[str, Any]] = []
    frozen: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    # 1. Портал: новые upcoming-матчи Wallachia → импорт без дублей.
    cache_path = CACHE_DIR / "liquipedia_matches_portal.json"
    try:
        portal = refresh_matches_portal(cache_path, client=httpx.Client())
    except (httpx.HTTPError, ValueError, OSError) as exc:
        portal = {"matches": [], "page_errors": [str(exc)]}
    existing_labels = {
        (row[0].strip().lower(), row[1].strip().lower())
        for row in db.execute(
            text(
                "SELECT team_a_label, team_b_label FROM scheduled_match "
                "WHERE status IN ('upcoming', 'frozen', 'played')"
            )
        ).all()
    }
    for match in portal.get("matches", []):
        if match.get("finished"):
            continue
        if "Wallachia" not in (match.get("tournament") or ""):
            continue
        pair = (match["teams"][0].strip().lower(), match["teams"][1].strip().lower())
        if pair in existing_labels:
            continue
        row = db.execute(
            text(
                """
                INSERT INTO scheduled_match
                    (tournament_label, team_a_label, team_b_label, stage_label,
                     scheduled_at, notes)
                VALUES
                    (:tournament, :team_a, :team_b, :stage, :scheduled_at, :notes)
                RETURNING id
                """
            ),
            {
                "tournament": match.get("tournament") or "Liquipedia",
                "team_a": match["teams"][0],
                "team_b": match["teams"][1],
                "stage": f"Bo{match['bestof']}" if match.get("bestof") else None,
                "scheduled_at": (
                    datetime.fromisoformat(match["started_at"])
                    if match.get("started_at")
                    else None
                ),
                "notes": "auto-import from Liquipedia portal (auto-freeze)",
            },
        ).scalar_one()
        existing_labels.add(pair)
        imported.append({"id": str(row), "teams": f"{match['teams'][0]} vs {match['teams'][1]}"})
    db.commit()

    # 2. Freeze за 10 минут до старта; после старта — честный skipped.
    upcoming_rows = db.execute(
        text(
            "SELECT id, team_a_label, team_b_label, scheduled_at FROM scheduled_match "
            "WHERE status = 'upcoming' AND scheduled_at IS NOT NULL"
        )
    ).all()
    for row in upcoming_rows:
        start = row.scheduled_at
        if start.tzinfo is None:
            from datetime import UTC

            start = start.replace(tzinfo=UTC)
        label = f"{row.team_a_label} vs {row.team_b_label}"
        if now >= start:
            db.execute(
                text(
                    "UPDATE scheduled_match SET status = 'cancelled', notes = "
                    "COALESCE(notes || ' | ', '') || 'missed_start: старт прошёл без заморозки', "
                    "updated_at = now() WHERE id = CAST(:id AS uuid)"
                ),
                {"id": str(row.id)},
            )
            skipped.append({"teams": label, "reason": "старт уже прошёл — честная заморозка невозможна"})
            continue
        if start - now <= timedelta(minutes=10):
            try:
                result = freeze_fixture(str(row.id), db)
                frozen.append(
                    {
                        "teams": label,
                        "freeze_id": result.get("freeze_id"),
                        "start": start.isoformat(),
                    }
                )
            except HTTPException as exc:
                skipped.append({"teams": label, "reason": str(exc.detail)[:200]})
    db.commit()
    if imported or frozen:
        lines = []
        if imported:
            lines.append("Импортировано: " + "; ".join(i["teams"] for i in imported))
        for f_item in frozen:
            lines.append(
                f"Заморожено: {f_item['teams']} (freeze {str(f_item['freeze_id'])[:8]}, старт {f_item['start']})"
            )
        notify_telegram("d2intel:\n" + "\n".join(lines))
    return {
        "checked_at": now.isoformat(),
        "imported": imported,
        "frozen": frozen,
        "skipped": skipped,
        "portal_errors": portal.get("page_errors", []),
    }


@router.get("/live-draft")
def live_draft_snapshot(db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Живой драфт для ближайшей замороженной фикстуры (ADR-008 фаза 2)."""
    row = db.execute(
        text(
            "SELECT team_a_label, team_b_label, tournament_label "
            "FROM scheduled_match "
            "WHERE status = 'frozen' ORDER BY scheduled_at ASC NULLS LAST LIMIT 1"
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Нет замороженных фикстур для live-наблюдения",
        )
    # Приоритет: STRATZ (пики + баны, лимит free-tier жёсткий — раз в минуту),
    # fallback OpenDota /live (только пики).
    stratz_match = None
    stratz_error = None
    try:
        from d2intel.ingestion.live_draft import stratz_live_match

        stratz_match = stratz_live_match(
            team_a=row.team_a_label, team_b=row.team_b_label, client=httpx.Client()
        )
    except (httpx.HTTPError, ValueError) as exc:
        stratz_error = str(exc)[:200]
    if stratz_match is not None:
        league = stratz_match.get("league") or {}
        result: dict[str, Any] = {
            "searching_for": f"{row.team_a_label} vs {row.team_b_label}",
            "found": True,
            "source": "stratz",
            "series_id": stratz_match.get("matchId"),
            "league_name": (league or {}).get("displayName"),
            "game_time_seconds": stratz_match.get("gameTime"),
            "radiant_score": stratz_match.get("radiantScore"),
            "dire_score": stratz_match.get("direScore"),
            "radiant_team": (stratz_match.get("radiantTeam") or {}).get("name"),
            "dire_team": (stratz_match.get("direTeam") or {}).get("name"),
            "radiant_picks": [],
            "dire_picks": [],
            "picks_count": 0,
            "note": "Драфт из STRATZ (пики; баны — если поле присутствует в live-схеме)",
        }
        picks_total = 0
        from d2intel.ingestion.live_draft import load_hero_names

        hero_names = load_hero_names()
        for player in stratz_match.get("players", []):
            hero_id = player.get("heroId")
            entry = {
                "player": None,
                "account_id": None,
                "hero_id": hero_id,
                "hero": hero_names.get(int(hero_id)) if hero_id else None,
                "slot": player.get("slot"),
                "team": player.get("team"),
            }
            picks_total += 1 if hero_id else 0
            (result["radiant_picks"] if player.get("team") == 0 else result["dire_picks"]).append(entry)
        result["picks_count"] = picks_total
        result["hero_names_missing"] = True
        return result
    if stratz_error:
        return {
            "searching_for": f"{row.team_a_label} vs {row.team_b_label}",
            "found": False,
            "source": "stratz",
            "message": f"STRATZ недоступен ({stratz_error}); повтор по лимиту free-tier.",
        }
    league_id = 20176 if "Wallachia" in (row.tournament_label or "") else None
    try:
        return live_draft_for(
            team_a=row.team_a_label,
            team_b=row.team_b_label,
            league_id=league_id,
            client=httpx.Client(),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"OpenDota live недоступен: {exc}",
        ) from exc


@router.post("/{fixture_id}/draft")
def save_draft_observation(
    fixture_id: str, payload: DraftObservation, db: Session = Depends(get_db)  # noqa: B008
) -> dict[str, Any]:
    """Сохранить наблюдаемый драфт как данные Gate-2 (не вход модели)."""
    _load_row(db, fixture_id)
    db.execute(
        text(
            "UPDATE scheduled_match SET draft_observed = CAST(:draft AS jsonb), "
            "updated_at = now() WHERE id = CAST(:id AS uuid)"
        ),
        {"draft": json.dumps(payload.draft, ensure_ascii=False), "id": fixture_id},
    )
    db.commit()
    updated = _load_row(db, fixture_id)
    updated["draft_note"] = _DRAFT_NOTE
    return updated
