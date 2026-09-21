# ADR-002 — История и расписание: разные источники

**Статус:** Proposed; operational доступ не подтверждён этим ADR.

**Контекст:** OpenDota historical API не является upcoming-календарём; проект ограничен бесплатными источниками и содержит будущий market-анализ.

**Предложение:** OpenDota — primary historical candidate после bounded coverage/rights audit. Liquipedia API — conditional upcoming/announced-roster candidate, только разрешённый API, без HTML scraping. STRATZ — optional secondary после token/schema проверки. PandaScore — вне critical path до письменного подтверждения допустимости сценария с market/edge/backtest.

**Альтернативы:** использовать только исторический OpenDota для первого прототипа; поменять источник, если бесплатный schedule gate не пройден. Community bridge не обход ToS и не независимый первоисточник.

**Последствия:** нужен EntityMapping, quarantine неоднозначных team/fixture matches, отдельный freshness/coverage отчёт. Upcoming no-go при working history оставляет ретроспективный прототип, но не закрывает полноценный MVP. History no-go блокирует INF-001.

**Основания:** SOURCES.md, U1–U15; [OpenDota docs](https://docs.opendota.com/), [Liquipedia ToS](https://liquipedia.net/api-terms-of-use), [PandaScore pricing/use restrictions](https://www.pandascore.co/pricing).

**Условия принятия:** SRC-001 фиксирует реальные данные/headers/coverage, права хранения и доступ; владелец принимает gate. Изменение провайдера не меняет canonical model без отдельного ADR.
