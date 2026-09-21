"""d2intel — Dota Esports Intelligence Platform (local skeleton, INF-001).

Только инфраструктура: инициализация, конфигурация, подключение к БД,
health-эндпоинт. Доменная логика (модели, фичи, ML, ingestion, prediction)
намеренно отсутствует — это задачи DB-001 / ING-001 / DATA-001 / FEAT-001 /
ML-001 и далее. Временная семантика (cutoff, as-of, snapshots) не трогается.
"""

__version__ = "0.0.1"
