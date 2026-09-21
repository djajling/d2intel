"""DATA-001 — нормализация исторического ядра (canonical-слой).

Разделение ответственности:

* `policy` — версии правил, коды карантина;
* `identity` — детерминированные canonical id;
* `payloads` — разбор сырого JSON в типизированные записи;
* `map_index` — вывод серии и номера карты (чистая функция, без БД);
* `temporal` — временной конверт canonical-записи;
* `quarantine` — карантин стадии нормализации;
* `writers` — идемпотентная запись canonical-строк;
* `pipeline` — оркестрация этапов.
"""

from __future__ import annotations

__all__ = ["identity", "map_index", "payloads", "pipeline", "policy", "quarantine", "writers"]
