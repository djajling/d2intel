"""Заморозка сплита: heldout фиксируется до обучения и не пересчитывается позже.

`ML-001` требует «замороженный heldout, не используемый для подбора». Заморозка
здесь — это не отдельная таблица, а **манифест**: детерминированное распределение
когорты по сегментам вместе с хэшем. Манифест коммитится в репозиторий до
обучания — это и есть pre-registration.

Зачем нужен хэш: дообписание приносит новые игры, в том числе в test-окно.
Состав test от этого меняется. Скрипт обучения сверяется с манифестом и
**падает**, если хэш разошёлся: тихо переобучиться на новом test — это именно
то, чего требует избежать ADR-006.

Что покрывает `content_hash`: спеку (границы + embargo), количество наблюдений
по сегментам и отсортированные id серий и игр в каждом сегменте. Если в уже
замороженную серию прилетит вторая карта-1 (remake) — хэш тоже изменится.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from d2intel.evaluation.cohort import Game1Row
from d2intel.evaluation.split import (
    SplitName,
    SplitSpec,
    assert_groups_do_not_straddle,
    assign_split,
)

SEGMENTS: tuple[SplitName, ...] = ("train", "valid", "test")
EXCLUDED_KEY = "excluded"


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _segment_payload(rows: list[Game1Row]) -> str:
    """Канонизированное содержимое одного сегмента: серии и игры, отсортированные."""
    return json.dumps(
        {
            "series": sorted(str(row.series_id) for row in rows),
            "games": sorted(str(row.game_id) for row in rows),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def content_hash_of(rows: list[Game1Row], spec: SplitSpec) -> str:
    """Хэш состава когорты по заданной спеке. Не зависит от порядка строк."""
    splits = [assign_split(row.event_time, spec) for row in rows]
    assert_groups_do_not_straddle(groups=[row.group for row in rows], splits=splits)

    by_segment: dict[SplitName, list[Game1Row]] = {name: [] for name in SEGMENTS}
    n_excluded = 0
    for row, split in zip(rows, splits, strict=True):
        if split is None:
            n_excluded += 1
        else:
            by_segment[split].append(row)

    segment_hashes: dict[str, str] = {
        name: _sha256(_segment_payload(by_segment[name])) for name in SEGMENTS
    }
    counts: dict[str, int] = {name: len(by_segment[name]) for name in SEGMENTS}
    counts[EXCLUDED_KEY] = n_excluded
    payload = json.dumps(
        {
            "valid_from": spec.valid_from.isoformat(),
            "test_from": spec.test_from.isoformat(),
            "embargo_seconds": spec.embargo.total_seconds(),
            "counts": counts,
            "segments": segment_hashes,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _sha256(payload)


@dataclass(frozen=True)
class FrozenSplit:
    """Замороженное распределение когорты по сегментам (pre-registration)."""

    spec: SplitSpec
    counts: dict[str, int]
    segment_hashes: dict[str, str]
    content_hash: str
    frozen_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": {
                "valid_from": self.spec.valid_from.isoformat(),
                "test_from": self.spec.test_from.isoformat(),
                "embargo_seconds": self.spec.embargo.total_seconds(),
            },
            "counts": dict(self.counts),
            "segment_hashes": dict(self.segment_hashes),
            "content_hash": self.content_hash,
            "frozen_at": self.frozen_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FrozenSplit:
        spec_payload = data["spec"]
        spec = SplitSpec(
            valid_from=datetime.fromisoformat(spec_payload["valid_from"]),
            test_from=datetime.fromisoformat(spec_payload["test_from"]),
            embargo=timedelta(seconds=spec_payload["embargo_seconds"]),
        )
        return cls(
            spec=spec,
            counts=dict(data["counts"]),
            segment_hashes=dict(data["segment_hashes"]),
            content_hash=data["content_hash"],
            frozen_at=datetime.fromisoformat(data["frozen_at"]),
        )


def freeze_split(
    rows: list[Game1Row], spec: SplitSpec, *, frozen_at: datetime
) -> FrozenSplit:
    """Построить манифест заморозки. Повторный вызов на тех же данных даёт тот же хэш."""
    splits = [assign_split(row.event_time, spec) for row in rows]
    assert_groups_do_not_straddle(groups=[row.group for row in rows], splits=splits)

    by_segment: dict[SplitName, list[Game1Row]] = {name: [] for name in SEGMENTS}
    n_excluded = 0
    for row, split in zip(rows, splits, strict=True):
        if split is None:
            n_excluded += 1
        else:
            by_segment[split].append(row)

    counts: dict[str, int] = {name: len(by_segment[name]) for name in SEGMENTS}
    counts[EXCLUDED_KEY] = n_excluded
    segment_hashes: dict[str, str] = {
        name: _sha256(_segment_payload(by_segment[name])) for name in SEGMENTS
    }
    return FrozenSplit(
        spec=spec,
        counts=counts,
        segment_hashes=segment_hashes,
        content_hash=content_hash_of(rows, spec),
        frozen_at=frozen_at,
    )


class FrozenSplitMismatch(ValueError):
    """Состав когорты разошёлся с замороженным манифестом."""


def assert_frozen_matches(rows: list[Game1Row], frozen: FrozenSplit) -> None:
    """Падает, если когорта изменилась после заморозки.

    Сверяется только состав данных (`content_hash`); `frozen_at` — это
    метка времени самой заморозки и в хэш не входит.
    """
    actual = content_hash_of(rows, frozen.spec)
    if actual != frozen.content_hash:
        raise FrozenSplitMismatch(
            "состав когорты изменился после заморозки: "
            f"manifest={frozen.content_hash} actual={actual}. "
            "Замороженный heldout зафиксирован до обучения (ML-001/ADR-006); "
            "дообписание добавило новые игры в замороженный диапазон. "
            "Расширьте диапазон новой заморозкой и явно её задокументируйте — "
            "но не переобучайтесь тихо на изменившемся test."
        )


def series_ids_of(rows: list[Game1Row]) -> list[UUID]:
    """Все id серий когорты — для отчётов и проверки уникальности примера на серию."""
    return [row.series_id for row in rows]
