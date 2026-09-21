"""initial temporal core schema (DB-001)

Создаёт минимальное ядро: raw-слой (JSONB), canonical (типизированные таблицы с
PK/FK/индексами) и снимки прогноза со снимками фичей.

Временной конверт (пять полей из docs/PRD_TEMPORAL.md) присутствует на всех
версионируемых таблицах: event_time, source_published_at, observed_at,
ingested_at, available_at + system_from/system_to.

Неизменяемость снимков enforced триггерами (ADR-005): UPDATE/DELETE запрещены.

Revision ID: 0001
Revises: None
Create Date: 2026-09-21

"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


# Одна инструкция = один элемент списка. Разбиение вручную, а не по ";",
# чтобы тела trigger-функций (с точкой с запятой внутри $$ ... $$) не ломались.
UP_STATEMENTS: list[str] = [
    # ---------- служебная функция: запрет мутации снимков ----------
    """
    CREATE FUNCTION d2intel_forbid_snapshot_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION
            'table % is immutable: UPDATE/DELETE forbidden (ADR-005)', TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """,
    # ---------- raw слой ----------
    """
    CREATE TABLE data_source (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name text NOT NULL,
        adapter_version text,
        capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
        terms_url text,
        terms_checked_at timestamptz,
        allowed_purposes text[],
        retention_policy text,
        created_at timestamptz NOT NULL DEFAULT now()
    );
    """,
    """
    CREATE TABLE ingestion_run (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_id uuid NOT NULL REFERENCES data_source(id),
        started_at timestamptz NOT NULL,
        finished_at timestamptz,
        status text NOT NULL,
        cursor_before text,
        cursor_after text,
        error_summary text,
        quota_headers jsonb,
        CONSTRAINT ingestion_run_interval CHECK (finished_at IS NULL OR finished_at >= started_at)
    );
    """,
    """
    CREATE TABLE raw_payload (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_id uuid NOT NULL REFERENCES data_source(id),
        endpoint_kind text NOT NULL,
        content_hash text NOT NULL,
        schema_version text NOT NULL,
        payload_json jsonb NOT NULL,
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT raw_payload_content_unique UNIQUE (source_id, content_hash),
        CONSTRAINT raw_payload_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT raw_payload_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE TABLE source_observation (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        run_id uuid REFERENCES ingestion_run(id),
        raw_payload_id uuid NOT NULL REFERENCES raw_payload(id),
        provider_entity_id text,
        provider_entity_type text,
        request_fingerprint text,
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT source_observation_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT source_observation_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    # ---------- canonical: соревнования и идентичность ----------
    """
    CREATE TABLE team (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        canonical_name text NOT NULL,
        identity_status text NOT NULL DEFAULT 'unresolved',
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT team_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT team_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE TABLE player (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id bigint,
        canonical_name text NOT NULL,
        identity_status text NOT NULL DEFAULT 'unresolved',
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT player_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT player_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE TABLE tournament (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name text NOT NULL,
        organizer_source text,
        starts_at timestamptz,
        ends_at timestamptz,
        tier_evidence jsonb,
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT tournament_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT tournament_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE TABLE series (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tournament_id uuid REFERENCES tournament(id),
        best_of smallint,
        score_a smallint,
        score_b smallint,
        status text NOT NULL DEFAULT 'unknown',
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT series_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT series_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE TABLE game (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        series_id uuid REFERENCES series(id),
        map_number smallint,
        attempt_number smallint NOT NULL DEFAULT 1,
        status text NOT NULL DEFAULT 'unknown',
        winner_team_id uuid REFERENCES team(id),
        result_type text,
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT game_map_attempt_unique UNIQUE (series_id, map_number, attempt_number),
        CONSTRAINT game_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT game_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE TABLE game_team (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        game_id uuid NOT NULL REFERENCES game(id),
        team_id uuid NOT NULL REFERENCES team(id),
        side text,
        slot smallint NOT NULL,
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT game_team_slot_unique UNIQUE (game_id, slot),
        CONSTRAINT game_team_side CHECK (side IS NULL OR side IN ('radiant', 'dire')),
        CONSTRAINT game_team_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT game_team_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE TABLE game_participant (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        game_id uuid NOT NULL REFERENCES game(id),
        player_id uuid NOT NULL REFERENCES player(id),
        team_id uuid REFERENCES team(id),
        hero_id integer,
        slot smallint NOT NULL,
        role text,
        roster_evidence jsonb,
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT game_participant_player_unique UNIQUE (game_id, player_id),
        CONSTRAINT game_participant_slot_unique UNIQUE (game_id, slot),
        CONSTRAINT game_participant_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT game_participant_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    # ---------- снимки и воспроизводимость ----------
    """
    CREATE TABLE model_version (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        algorithm text NOT NULL,
        artifact_uri text,
        artifact_hash text,
        code_commit text,
        dependency_lock_hash text,
        dataset_id uuid,
        training_cutoff timestamptz,
        hyperparameters jsonb,
        seed bigint,
        feature_schema_version text NOT NULL,
        promotion_status text NOT NULL DEFAULT 'candidate',
        computed_at timestamptz NOT NULL DEFAULT now()
    );
    """,
    """
    CREATE TABLE feature_snapshot (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        target_type text NOT NULL,
        target_game_id uuid REFERENCES game(id),
        target_series_id uuid REFERENCES series(id),
        cutoff_at timestamptz NOT NULL,
        evaluation_mode text NOT NULL,
        values_json jsonb NOT NULL,
        coverage_json jsonb NOT NULL DEFAULT '{}'::jsonb,
        feature_schema_version text NOT NULL,
        content_hash text NOT NULL,
        assumed_available_at timestamptz,
        lag_policy_version text,
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT feature_snapshot_target_type CHECK (target_type IN ('game', 'series')),
        CONSTRAINT feature_snapshot_target_xor
            CHECK ((target_game_id IS NOT NULL) <> (target_series_id IS NOT NULL)),
        CONSTRAINT feature_snapshot_mode CHECK (
            evaluation_mode IN ('retrospective_reconstructed', 'prospective_observed')
        ),
        CONSTRAINT feature_snapshot_lag_policy CHECK (
            (evaluation_mode = 'prospective_observed' AND assumed_available_at IS NULL)
            OR (evaluation_mode = 'retrospective_reconstructed' AND lag_policy_version IS NOT NULL)
        ),
        CONSTRAINT feature_snapshot_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT feature_snapshot_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE TABLE prediction (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        target_type text NOT NULL,
        target_game_id uuid REFERENCES game(id),
        target_series_id uuid REFERENCES series(id),
        team_a_id uuid NOT NULL REFERENCES team(id),
        team_b_id uuid NOT NULL REFERENCES team(id),
        phase_contract text,
        request_key text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT prediction_target_type CHECK (target_type IN ('game', 'series')),
        CONSTRAINT prediction_target_xor
            CHECK ((target_game_id IS NOT NULL) <> (target_series_id IS NOT NULL)),
        CONSTRAINT prediction_teams_distinct CHECK (team_a_id <> team_b_id),
        CONSTRAINT prediction_request_key_unique UNIQUE (request_key)
    );
    """,
    """
    CREATE TABLE prediction_snapshot (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        prediction_id uuid NOT NULL REFERENCES prediction(id),
        snapshot_seq integer NOT NULL,
        computed_at timestamptz NOT NULL,
        cutoff_at timestamptz NOT NULL,
        model_version_id uuid REFERENCES model_version(id),
        feature_snapshot_id uuid REFERENCES feature_snapshot(id),
        p_a double precision,
        p_b double precision,
        abstention_reason text,
        evaluation_mode text NOT NULL,
        state_hash text NOT NULL,
        idempotency_key text NOT NULL,
        event_time timestamptz,
        source_published_at timestamptz,
        observed_at timestamptz NOT NULL,
        ingested_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        system_from timestamptz NOT NULL DEFAULT now(),
        system_to timestamptz,
        CONSTRAINT prediction_snapshot_seq_unique UNIQUE (prediction_id, snapshot_seq),
        CONSTRAINT prediction_snapshot_idem_unique UNIQUE (idempotency_key),
        CONSTRAINT prediction_snapshot_mode CHECK (
            evaluation_mode IN ('retrospective_reconstructed', 'prospective_observed')
        ),
        CONSTRAINT prediction_snapshot_probability CHECK (
            (p_a IS NULL AND p_b IS NULL AND abstention_reason IS NOT NULL)
            OR (p_a IS NOT NULL AND p_b IS NOT NULL)
        ),
        CONSTRAINT prediction_snapshot_temporal_order
            CHECK (observed_at <= ingested_at AND ingested_at <= available_at),
        CONSTRAINT prediction_snapshot_system_interval
            CHECK (system_to IS NULL OR system_from < system_to)
    );
    """,
    """
    CREATE TABLE snapshot_evidence (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        snapshot_id uuid NOT NULL REFERENCES prediction_snapshot(id),
        evidence_id uuid NOT NULL,
        role text NOT NULL,
        CONSTRAINT snapshot_evidence_role CHECK (role IN ('source', 'feature', 'attribution')),
        CONSTRAINT snapshot_evidence_unique UNIQUE (snapshot_id, evidence_id, role)
    );
    """,
    """
    CREATE TABLE prediction_evaluation (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        snapshot_id uuid NOT NULL REFERENCES prediction_snapshot(id),
        result_revision_id uuid,
        metric_definition_version text NOT NULL,
        y boolean,
        log_loss double precision,
        brier double precision,
        exclusion_reason text,
        evaluated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT prediction_evaluation_unique
            UNIQUE (snapshot_id, result_revision_id, metric_definition_version)
    );
    """,
    # ---------- индексы ----------
    "CREATE INDEX idx_raw_payload_source ON raw_payload (source_id);",
    "CREATE INDEX idx_source_observation_payload ON source_observation (raw_payload_id);",
    "CREATE INDEX idx_game_series ON game (series_id);",
    "CREATE INDEX idx_game_team_game ON game_team (game_id);",
    "CREATE INDEX idx_game_participant_game ON game_participant (game_id);",
    "CREATE INDEX idx_feature_snapshot_cutoff ON feature_snapshot (cutoff_at);",
    "CREATE INDEX idx_prediction_snapshot_prediction ON prediction_snapshot (prediction_id);",
    "CREATE INDEX idx_prediction_evaluation_snapshot ON prediction_evaluation (snapshot_id);",
    # ---------- неизменяемость снимков (ADR-005) ----------
    """
    CREATE TRIGGER model_version_no_mutation
        BEFORE UPDATE OR DELETE ON model_version
        FOR EACH ROW EXECUTE FUNCTION d2intel_forbid_snapshot_mutation();
    """,
    """
    CREATE TRIGGER feature_snapshot_no_mutation
        BEFORE UPDATE OR DELETE ON feature_snapshot
        FOR EACH ROW EXECUTE FUNCTION d2intel_forbid_snapshot_mutation();
    """,
    """
    CREATE TRIGGER prediction_snapshot_no_mutation
        BEFORE UPDATE OR DELETE ON prediction_snapshot
        FOR EACH ROW EXECUTE FUNCTION d2intel_forbid_snapshot_mutation();
    """,
    """
    CREATE TRIGGER snapshot_evidence_no_mutation
        BEFORE UPDATE OR DELETE ON snapshot_evidence
        FOR EACH ROW EXECUTE FUNCTION d2intel_forbid_snapshot_mutation();
    """,
]

DOWN_STATEMENTS: list[str] = [
    "DROP TRIGGER IF EXISTS snapshot_evidence_no_mutation ON snapshot_evidence;",
    "DROP TRIGGER IF EXISTS prediction_snapshot_no_mutation ON prediction_snapshot;",
    "DROP TRIGGER IF EXISTS feature_snapshot_no_mutation ON feature_snapshot;",
    "DROP TRIGGER IF EXISTS model_version_no_mutation ON model_version;",
    "DROP INDEX IF EXISTS idx_prediction_evaluation_snapshot;",
    "DROP INDEX IF EXISTS idx_prediction_snapshot_prediction;",
    "DROP INDEX IF EXISTS idx_feature_snapshot_cutoff;",
    "DROP INDEX IF EXISTS idx_game_participant_game;",
    "DROP INDEX IF EXISTS idx_game_team_game;",
    "DROP INDEX IF EXISTS idx_game_series;",
    "DROP INDEX IF EXISTS idx_source_observation_payload;",
    "DROP INDEX IF EXISTS idx_raw_payload_source;",
    "DROP TABLE IF EXISTS prediction_evaluation;",
    "DROP TABLE IF EXISTS snapshot_evidence;",
    "DROP TABLE IF EXISTS prediction_snapshot;",
    "DROP TABLE IF EXISTS prediction;",
    "DROP TABLE IF EXISTS feature_snapshot;",
    "DROP TABLE IF EXISTS model_version;",
    "DROP TABLE IF EXISTS game_participant;",
    "DROP TABLE IF EXISTS game_team;",
    "DROP TABLE IF EXISTS game;",
    "DROP TABLE IF EXISTS series;",
    "DROP TABLE IF EXISTS tournament;",
    "DROP TABLE IF EXISTS player;",
    "DROP TABLE IF EXISTS team;",
    "DROP TABLE IF EXISTS source_observation;",
    "DROP TABLE IF EXISTS raw_payload;",
    "DROP TABLE IF EXISTS ingestion_run;",
    "DROP TABLE IF EXISTS data_source;",
    "DROP FUNCTION IF EXISTS d2intel_forbid_snapshot_mutation();",
]


def upgrade() -> None:
    """Применить схему."""
    for statement in UP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Откатить схему (обратно и воспроизводимо)."""
    for statement in DOWN_STATEMENTS:
        op.execute(statement)
