# REPO_SETUP.md — настройка репозитория проекта

> Только про **инфраструктуру git**: инициализация, приватный remote, рабочий процесс
> — в согласовании с `README.md` и протоколом «AI coding assistant».
> **Этот документ не разрешает реализацию** `SRC-001` / `INF-001` и далее —
> они остаются `Planned` до решения владельца. Здесь не создаются пустые
> сервисы/абстракции (см. `ARCHITECTURE.md` §7).

## Зачем

Рабочий протокол проекта: «выбрать задачу → прочитать архитектуру/код → план →
тесты → реализация → review → обновить документацию → **commit в согласованном
репозитории**». Репозиторий — единственное место, где фиксируется история и
вероятный remote для бэкапа. Пока это локальная папка документов без git.

## Задача GitHub (инфраструктурная, не продуктовая)

- Создать **приватный** репозиторий на GitHub (бесплатно, безлимит).
- Привязать локальный git к remote.
- Использовать **GitHub Issues** как лёгкий трекер задач (без Jira/Confluence —
  см. рекомендации агента) ИЛИ вести `CURRENT TASK` прямо в `README.md`.
- **GitHub Actions** — будущий бесплатный CI для тестов (темы `INF-001`, ML-пайплайн).

## Шаги

### 1. Инициализировать локальный git

```bash
cd /sdcard/Documents/37220e6644bc_dota-intelligence-plan/dota-intelligence
git init -b main
```

### 2. Настроить пользователя (один раз)

```bash
git config user.name  "Your Name"
git config user.email "you@example.com"
```

### 3. Создать приватный репозиторий на GitHub

Через веб-интерфейс: **New repository** → имя, например `dota-intelligence`
→ **Private** → не создавать README (он уже есть) → Create.

Через CLI ([gh](https://cli.github.com/), бесплатно):

```bash
gh auth login
gh repo create dota-intelligence --private --source . --remote origin --push
```

### 4. Первый коммит

```bash
git add -A
git commit -m "docs: initial project documentation package (ADRs, backlog, architecture)"
git branch -M main
git push -u origin main
```

### 5. Дальше — по протоколу

- `PRD-001` ещё `Proposed`: до одобрения владельцем никакие задачи не начинаются.
- После одобрения — `SRC-001` (bounded read-only audit источников), затем `INF-001`
  (реальный скелет репозитория + smoke test) создаст `docker-compose.yml`,
  `src/`, `tests/` — **не сейчас**.

## Соглашения коммитов (предложение, под согласование)

- `docs:` — документация/ADR (текущий этап).
- `feat:`, `fix:`, `test:`, `chore:`, `refactor:` — по мере кода.
- Ссылка на задачу в сообщении, напр. `INF-001: ...`.

## Что НЕ делается на этом этапе

- Никаких пустых `src/`, `tests/`, `docker-compose.yml` — это тело задачи `INF-001`,
  она `Planned`, не начата (по `FIRST_10_TASKS.md` и `ARCHITECTURE.md` §7).
- Никаких автоматических scheduled/recurring задач здесь.
- Никаких обходов гейтов и источников без решения владельца.
