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
