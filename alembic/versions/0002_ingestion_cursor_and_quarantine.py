"""ingestion cursor + quarantine (ING-001)

Дополняет raw-слой `DB-001` двумя таблицами, которые нужны механизмам
`ING-001` (ARCHITECTURE.md §3, пп. 4–6):

* `ingestion_cursor` — персистентный watermark пагинации. Обновляется **только
  после** успешного commit raw-данных. Это operational checkpoint, а не
  версионируемый факт: временной конверт из `docs/PRD_TEMPORAL.md` здесь
  намеренно не дублируется (нет `observed_at`/`available_at` — курсор не
  является наблюдением источника).
* `ingestion_quarantine` — карантин повреждённых/непригодных строк с отдельной
  data-quality причиной. Временной конверт присутствует: карантин фиксирует
  момент наблюдения проблемной строки.

Сырой payload при карантине **не теряется**: он уже записан в `raw_payload`,
карантин хранит ссылку (run, fingerprint, content_hash) и причину.

Миграция аддитивная и обратимая.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21

"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


UP_STATEMENTS: list[str] = [
    # ---------- watermark пагинации ----------
    """
    CREATE TABLE ingestion_cursor (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_id uuid NOT NULL REFERENCES data_source(id),
        endpoint_kind text NOT NULL,
        cursor_value text,
        cursor_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        last_run_id uuid REFERENCES ingestion_run(id),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ingestion_cursor_unique UNIQUE (source_id, endpoint_kind)
    );
    """,
    # ---------- карантин ----------
    """
    CREATE TABLE ingestion_quarantine (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        run_id uuid REFERENCES ingestion_run(id),
        source_id uuid NOT NULL REFERENCES data_source(id),
        endpoint_kind text NOT NULL,
        reason_code text NOT NULL,
        reason_detail text,
        provider_entity_id text,
        provider_entity_type text,
        request_fingerprint text,
        content_hash text NOT NULL,
        offending_payload jsonb,
        status text NOT NULL DEFAULT 'open',
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT ingestion_quarantine_reason_present
            CHECK (length(btrim(reason_code)) > 0),
        CONSTRAINT ingestion_quarantine_status
            CHECK (status IN ('open', 'resolved')),
        CONSTRAINT ingestion_quarantine_unique
            UNIQUE (source_id, content_hash, reason_code),
        CONSTRAINT ingestion_quarantine_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT ingestion_quarantine_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    "CREATE INDEX idx_ingestion_cursor_source ON ingestion_cursor (source_id);",
    "CREATE INDEX idx_ingestion_quarantine_run ON ingestion_quarantine (run_id);",
    "CREATE INDEX idx_ingestion_quarantine_source ON ingestion_quarantine (source_id);",
    "CREATE INDEX idx_ingestion_quarantine_reason ON ingestion_quarantine (reason_code);",
]

DOWN_STATEMENTS: list[str] = [
    "DROP INDEX IF EXISTS idx_ingestion_quarantine_reason;",
    "DROP INDEX IF EXISTS idx_ingestion_quarantine_source;",
    "DROP INDEX IF EXISTS idx_ingestion_quarantine_run;",
    "DROP INDEX IF EXISTS idx_ingestion_cursor_source;",
    "DROP TABLE IF EXISTS ingestion_quarantine;",
    "DROP TABLE IF EXISTS ingestion_cursor;",
]


def upgrade() -> None:
    """Применить схему ING-001."""
    for statement in UP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Откатить схему ING-001 (обратимо)."""
    for statement in DOWN_STATEMENTS:
        op.execute(statement)
