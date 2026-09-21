#!/usr/bin/env python3
"""Одноразовый entrypoint: проверка живости БД.

Не доменная логика. Запуск:
    python scripts/db_healthcheck.py
Возвращает код 0 при успехе, 1 при недоступной БД.
"""

from __future__ import annotations

from d2intel.db import check_db_connection, engine


def main() -> int:
    ok = check_db_connection(engine)
    print(f"database: {'up' if ok else 'down'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
