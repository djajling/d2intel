"""normalized core: provenance, patch, mapping, roster, performance (DATA-001)

Аддитивная и обратимая ревизия поверх `0002`. Что добавляет:

* **provenance** — `source_observation_id` NOT NULL на всех canonical-таблицах.
  Требование `DATA-001` AC#1 («каждая canonical-запись связана с raw»)
  проверяется схемой, а не соглашением;
* **`patch`** — минимальный справочник патчей + `game.patch_id`;
* **`entity_mapping`** — provider → canonical для identity-сущностей
  (team/player/tournament) с typed FK и XOR-check;
* **`roster_membership`** — ростер как **свидетельство с датами**: одна строка
  на (команда, игрок, игра), интервал = [начало игры, конец игры), ссылка на
  наблюдение-источник. Никакой mutable «текущий состав»;
* **`player_performance`** — финальная статистика карты **отдельной таблицей** с
  маркером `data_class` (AC#5): pre-match слой читает `game_participant`, а не её;
* **`normalization_quarantine`** — карантин стадии нормализации (неоднозначный
  map1, неполная серия, отсутствующая идентичность). Отдельная таблица, а не
  `ingestion_quarantine`: другой этап и другое пространство ключей
  (`job_kind` вместо `endpoint_kind`).

Сущности `Match` и `TournamentStage` из `DATA_MODEL.md` §3 здесь **не**
создаются: источник истории (`OpenDota`) не даёт ни stage-информации, ни
будущих матчей; пустой слой без writer'а не создаётся (принцип минимальной
необходимой сложности). Они появляются со своей задачей и своим источником.

Временной конверт (`docs/PRD_TEMPORAL.md`) добавлен на все новые
версионируемые таблицы.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-21

"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


UP_STATEMENTS: list[str] = [
    # ---------- provenance canonical-слоя ----------
    # NOT NULL намеренно: canonical-записи создаются только нормализацией, у
    # которой всегда есть наблюдение-источник. Если строки уже есть — сначала
    # backfill, потом миграция.
    """
    ALTER TABLE team
        ADD COLUMN source_observation_id uuid NOT NULL REFERENCES source_observation(id);
    """,
    """
    ALTER TABLE player
        ADD COLUMN source_observation_id uuid NOT NULL REFERENCES source_observation(id);
    """,
    """
    ALTER TABLE tournament
        ADD COLUMN source_observation_id uuid NOT NULL REFERENCES source_observation(id);
    """,
    """
    ALTER TABLE series
        ADD COLUMN source_observation_id uuid NOT NULL REFERENCES source_observation(id);
    """,
    """
    ALTER TABLE series
        ADD COLUMN series_key text NOT NULL;
    """,
    """
    ALTER TABLE game
        ADD COLUMN source_observation_id uuid NOT NULL REFERENCES source_observation(id);
    """,
    """
    ALTER TABLE game
        ADD COLUMN provider_match_id text NOT NULL;
    """,
    """
    ALTER TABLE game_team
        ADD COLUMN source_observation_id uuid NOT NULL REFERENCES source_observation(id);
    """,
    """
    ALTER TABLE game_participant
        ADD COLUMN source_observation_id uuid NOT NULL REFERENCES source_observation(id);
    """,
    # ---------- честная идентичность: имя может быть неизвестно ----------
    # NULL-имя допустимо только при identity_status = 'unresolved': неизвестное
    # значение не подменяется синтетическим.
    """
    ALTER TABLE team ALTER COLUMN canonical_name DROP NOT NULL;
    """,
    """
    ALTER TABLE team ADD CONSTRAINT team_name_or_unresolved
        CHECK (canonical_name IS NOT NULL OR identity_status = 'unresolved');
    """,
    """
    ALTER TABLE team ADD CONSTRAINT team_identity_status
        CHECK (identity_status IN ('unresolved', 'resolved', 'conflicted'));
    """,
    """
    ALTER TABLE player ALTER COLUMN canonical_name DROP NOT NULL;
    """,
    """
    ALTER TABLE player ADD CONSTRAINT player_name_or_unresolved
        CHECK (canonical_name IS NOT NULL OR identity_status = 'unresolved');
    """,
    """
    ALTER TABLE player ADD CONSTRAINT player_identity_status
        CHECK (identity_status IN ('unresolved', 'resolved', 'conflicted'));
    """,
    # Название лиги в источнике может отсутствовать (`league_name = null`):
    # NULL честнее синтетической подписи, ссылка на лигу при этом сохраняется.
    """
    ALTER TABLE tournament ALTER COLUMN name DROP NOT NULL;
    """,
    # ---------- справочник патчей ----------
    """
    CREATE TABLE patch (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        version_label text NOT NULL,
        patch_type text,
        effective_from timestamptz,
        effective_to timestamptz,
        announced_at timestamptz,
        evidence jsonb,
        source_observation_id uuid NOT NULL REFERENCES source_observation(id),
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT patch_version_unique UNIQUE (version_label),
        CONSTRAINT patch_type CHECK (patch_type IS NULL OR patch_type IN ('major', 'minor', 'hotfix')),
        CONSTRAINT patch_effective_interval
            CHECK (effective_to IS NULL OR (effective_from IS NOT NULL AND effective_from < effective_to)),
        CONSTRAINT patch_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT patch_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    ALTER TABLE game ADD COLUMN patch_id uuid REFERENCES patch(id);
    """,
    # ---------- provider -> canonical ----------
    """
    CREATE TABLE entity_mapping (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_id uuid NOT NULL REFERENCES data_source(id),
        entity_type text NOT NULL,
        external_id text NOT NULL,
        team_id uuid REFERENCES team(id),
        player_id uuid REFERENCES player(id),
        tournament_id uuid REFERENCES tournament(id),
        mapping_version text NOT NULL,
        status text NOT NULL DEFAULT 'active',
        source_observation_id uuid NOT NULL REFERENCES source_observation(id),
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT entity_mapping_type
            CHECK (entity_type IN ('team', 'player', 'tournament')),
        CONSTRAINT entity_mapping_status
            CHECK (status IN ('active', 'superseded', 'conflicted')),
        CONSTRAINT entity_mapping_target_xor
            CHECK (
                (CASE WHEN team_id IS NULL THEN 0 ELSE 1 END)
                + (CASE WHEN player_id IS NULL THEN 0 ELSE 1 END)
                + (CASE WHEN tournament_id IS NULL THEN 0 ELSE 1 END) = 1
            ),
        CONSTRAINT entity_mapping_target_matches_type
            CHECK (
                (entity_type = 'team' AND team_id IS NOT NULL)
                OR (entity_type = 'player' AND player_id IS NOT NULL)
                OR (entity_type = 'tournament' AND tournament_id IS NOT NULL)
            ),
        CONSTRAINT entity_mapping_version_unique
            UNIQUE (source_id, entity_type, external_id, mapping_version),
        CONSTRAINT entity_mapping_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT entity_mapping_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE UNIQUE INDEX entity_mapping_active_unique
        ON entity_mapping (source_id, entity_type, external_id)
     WHERE status = 'active';
    """,
    # ---------- ростер как свидетельство ----------
    """
    CREATE TABLE roster_membership (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        team_id uuid NOT NULL REFERENCES team(id),
        player_id uuid NOT NULL REFERENCES player(id),
        game_id uuid NOT NULL REFERENCES game(id),
        membership_type text NOT NULL,
        role text,
        is_standin boolean,
        valid_from timestamptz NOT NULL,
        valid_to timestamptz,
        evidence jsonb,
        source_observation_id uuid NOT NULL REFERENCES source_observation(id),
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT roster_membership_unique UNIQUE (team_id, player_id, game_id),
        CONSTRAINT roster_membership_type
            CHECK (membership_type IN ('actual_observed', 'announced', 'registered', 'inferred')),
        CONSTRAINT roster_membership_interval
            CHECK (valid_to IS NULL OR valid_from < valid_to),
        CONSTRAINT roster_membership_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT roster_membership_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    # ---------- финальная статистика карты (post-game) ----------
    """
    CREATE TABLE player_performance (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        game_participant_id uuid NOT NULL UNIQUE REFERENCES game_participant(id),
        metric_schema_version text NOT NULL,
        data_class text NOT NULL DEFAULT 'final',
        kills integer,
        deaths integer,
        assists integer,
        net_worth integer,
        gold_per_min integer,
        xp_per_min integer,
        last_hits integer,
        denies integer,
        hero_damage bigint,
        duration_seconds integer,
        source_observation_id uuid NOT NULL REFERENCES source_observation(id),
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT player_performance_data_class
            CHECK (data_class IN ('final', 'partial')),
        CONSTRAINT player_performance_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT player_performance_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    # ---------- карантин нормализации ----------
    """
    CREATE TABLE normalization_quarantine (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        job_kind text NOT NULL,
        source_id uuid NOT NULL REFERENCES data_source(id),
        source_observation_id uuid REFERENCES source_observation(id),
        provider_entity_id text,
        reason_code text NOT NULL,
        reason_detail text,
        offending_payload jsonb,
        status text NOT NULL DEFAULT 'open',
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT normalization_quarantine_reason_present
            CHECK (length(btrim(reason_code)) > 0),
        CONSTRAINT normalization_quarantine_status
            CHECK (status IN ('open', 'resolved')),
        CONSTRAINT normalization_quarantine_unique
            UNIQUE (job_kind, source_id, provider_entity_id, reason_code),
        CONSTRAINT normalization_quarantine_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT normalization_quarantine_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    # ---------- индексы ----------
    "CREATE INDEX idx_source_observation_provider_entity ON source_observation (provider_entity_id);",
    "CREATE INDEX idx_game_patch ON game (patch_id);",
    "CREATE INDEX idx_game_provider_match ON game (provider_match_id);",
    "CREATE INDEX idx_series_key ON series (series_key);",
    "CREATE INDEX idx_entity_mapping_lookup ON entity_mapping (source_id, entity_type, external_id);",
    "CREATE INDEX idx_roster_membership_team ON roster_membership (team_id, valid_from DESC);",
    "CREATE INDEX idx_roster_membership_player ON roster_membership (player_id, valid_from DESC);",
    "CREATE INDEX idx_normalization_quarantine_reason ON normalization_quarantine (reason_code);",
    "CREATE INDEX idx_normalization_quarantine_status ON normalization_quarantine (status);",
]

DOWN_STATEMENTS: list[str] = [
    "DROP INDEX IF EXISTS idx_normalization_quarantine_status;",
    "DROP INDEX IF EXISTS idx_normalization_quarantine_reason;",
    "DROP INDEX IF EXISTS idx_roster_membership_player;",
    "DROP INDEX IF EXISTS idx_roster_membership_team;",
    "DROP INDEX IF EXISTS idx_entity_mapping_lookup;",
    "DROP INDEX IF EXISTS idx_series_key;",
    "DROP INDEX IF EXISTS idx_game_provider_match;",
    "DROP INDEX IF EXISTS idx_game_patch;",
    "DROP INDEX IF EXISTS idx_source_observation_provider_entity;",
    "DROP TABLE IF EXISTS normalization_quarantine;",
    "DROP TABLE IF EXISTS player_performance;",
    "DROP TABLE IF EXISTS roster_membership;",
    "DROP INDEX IF EXISTS entity_mapping_active_unique;",
    "DROP TABLE IF EXISTS entity_mapping;",
    "ALTER TABLE game DROP COLUMN IF EXISTS patch_id;",
    "DROP TABLE IF EXISTS patch;",
    "ALTER TABLE tournament ALTER COLUMN name SET NOT NULL;",
    "ALTER TABLE player DROP CONSTRAINT IF EXISTS player_identity_status;",
    "ALTER TABLE player DROP CONSTRAINT IF EXISTS player_name_or_unresolved;",
    "ALTER TABLE team DROP CONSTRAINT IF EXISTS team_identity_status;",
    "ALTER TABLE team DROP CONSTRAINT IF EXISTS team_name_or_unresolved;",
    "ALTER TABLE game_participant DROP COLUMN IF EXISTS source_observation_id;",
    "ALTER TABLE game_team DROP COLUMN IF EXISTS source_observation_id;",
    "ALTER TABLE game DROP COLUMN IF EXISTS provider_match_id;",
    "ALTER TABLE game DROP COLUMN IF EXISTS source_observation_id;",
    "ALTER TABLE series DROP COLUMN IF EXISTS series_key;",
    "ALTER TABLE series DROP COLUMN IF EXISTS source_observation_id;",
    "ALTER TABLE tournament DROP COLUMN IF EXISTS source_observation_id;",
    "ALTER TABLE player DROP COLUMN IF EXISTS source_observation_id;",
    "ALTER TABLE team DROP COLUMN IF EXISTS source_observation_id;",
    # Симметрия: вернуть NOT NULL, который снят в upgrade. Выполняется последним,
    # когда ограничения уже сняты; при наличии строк с NULL-именами откат
    # потребует очистки данных (downgrade до base разрушителен по определению).
    "ALTER TABLE player ALTER COLUMN canonical_name SET NOT NULL;",
    "ALTER TABLE team ALTER COLUMN canonical_name SET NOT NULL;",
]


def upgrade() -> None:
    """Применить схему DATA-001."""
    for statement in UP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Откатить схему DATA-001 (обратимо)."""
    for statement in DOWN_STATEMENTS:
        op.execute(statement)
