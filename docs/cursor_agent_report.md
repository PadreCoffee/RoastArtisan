# Cursor agent report (краткий журнал)

## 2026-03-20 — Master-report по шаблону `07_report_template.md` + `assemble_reports_prompt.md`

- **Переписан** `docs/ask/artisan_research_master_report.md`: сверху блоки шаблона (Executive summary, Scope, Findings по 6 подсистемам, Key files, Confirmed, Uncertain U1–U6, Reuse/rewrite), затем полный раздел сборщика (противоречия, decomposition, классификация, рамка продукта, risk map, вопросы для brief, индекс `agent_01`–`agent_06`).
- **База:** все файлы `docs/ask/agent_0[1-6]_*.md` в репозитории.

## 2026-03-20 — Master-report: полная сборка по `assemble_reports_prompt.md`

- **Обновлён:** `docs/ask/artisan_research_master_report.md` — единый документ: executive synthesis по всем ASK 1–6 со ссылками на файлы, противоречия (вкл. U1), decomposition, таблица подсистем, рамка продукта, risk map, вопросы для brief, индекс с колонкой «статус».
- **Проверен:** `docs/ask/agent_05_ui_ux.md` — отчёт ASK-5 (карта UI, workflow, coupling, роли, таблица экранов).

## 2026-03-20 — Полный комплект ASK 01–06 + master-report

- **Созданы:** `docs/ask/agent_02_device_layer.md`, `agent_04_data_model.md`, `agent_05_ui_ux.md`, `agent_06_architecture_risks.md` по промптам из `artisan_research_package_v2/ask_prompts/` (обязательные таблицы и структура отчётов, якоря к `main.py`, `canvas.py`, `comm.py`, `modbusport.py`, `s7port.py`, `wsport.py`, `atypes.py`, `plus/*`).
- **Уже были:** `agent_01_core_logging.md`, `agent_03_artisan_plus.md`.
- **Пересобран:** `docs/ask/artisan_research_master_report.md` — единый синтез всех шести ASK, индекс файлов, таблица carry-over, риски, вопросы для brief; противоречий между ASK не выявлено (открыт пункт U1: полный аудит `ProfileData` ↔ save/load).

## 2026-03-20 — Master-report: формат `assemble_reports_prompt.md` *(история)*

- Промежуточная версия master; актуальное состояние — **все `agent_01`–`agent_06`** + обновлённый master (см. запись «Полный комплект» ниже).

## 2026-03-20 — ASK-3 + пересборка master-report

- **Создан:** `docs/ask/agent_03_artisan_plus.md` — карта `src/plus`, auth/session (`connection`), API-клиент, сериализация `getRoast`/`getSyncRecord`, lifecycle sync (queue + `fetchServerUpdate`), риски GPL/API, таблица компонентов, файлы для deep-dive.
- **Обновлён:** `docs/ask/artisan_research_master_report.md` — таблица источников (agent_03), executive synthesis (п.5–6), блок Artisan Plus со ссылкой на ASK-3, строка противоречий agent_01↔agent_03, классификация `plus/`, «следующие шаги».
- **Покрытие ASK-файлов:** готовы **01** (logging), **03** (Plus); нет **02/04/05/06** — материал частично остаётся в master.

## 2026-03-20 — ASK-1: core logging (отдельный .md)

- **Создан:** `docs/ask/agent_01_core_logging.md` — lifecycle ON/START, `SampleThread` → `sample_processing`, RoR (`compute_ror`), события (`timeindex`, `mark*`, `addEvent`), график (`updategraphics`, `redraw`), таблица компонентов и рекомендации по выносу.
- **Обновлён:** `docs/ask/artisan_research_master_report.md` — таблица источников (учтён agent_01), executive synthesis, блок Core logging, противоречия runtime vs snapshot, классификация `canvas.py`, архитектурный абзац, «следующие шаги».

## 2026-03-20 — Сборка master-report ASK

- **Действие:** пересобран `docs/ask/artisan_research_master_report.md` по промпту `assemble_reports_prompt.md`.
- **Факт:** в `docs/ask/` отсутствуют отдельные ASK-файлы (`agent_*`); единственный артефакт — master-report. В отчёте зафиксировано внутреннее противоречие прошлой версии (ссылка на «ASK-2» без файла) и усилен блок архитектуры/`plus` перепроверкой по `main.py`, `canvas.py`, `comm.py`, `plus/config.py`, `plus/controller.py`, `plus/queue.py`, `plus/sync.py`.
- **Следующий шаг для полноты:** записать промежуточные ASK в `docs/ask/*.md` и снова запустить сборщик.

## 2026-03-20 — Master-report: ASK-4 (data model)

- **Действие:** в `docs/ask/artisan_research_master_report.md` добавлен синтез **модели данных / persistence / import-export** (`ProfileData`, `getProfile`/`setProfile`, `.alog` через `repr`/`ast.literal_eval`, JSON/CSV, `QSettings`+`.aset`/`.athm`, alarms/alrm, Plus `getRoast`/sync hash, UUID shelve).
- **C1:** исправлена устаревшая трактовка «центр модели = `roast_properties.py`» — по коду центр — `main.py` + `atypes.py` + `util.py`.

## 2026-03-30 — `.alog` и внутренняя roast/session/profile model

Подготовлен детальный reverse engineering отчет: [docs/ask/alog_and_roast_data_model.md](/Users/lectrisheep/Documents/Projects/RoastArtisan/docs/ask/alog_and_roast_data_model.md).

Короткий итог:

- `.alog` реализован не как отдельная rich serialization subsystem, а как Python-literal save/load через `serialize()` / `deserialize()` в `src/artisanlib/util.py:973-986`.
- Runtime canonical state живет не в `.alog`, а в `self.qmc` (`tgraphcanvas`), который держит live curves, events, derived arrays, background profile и UI-related state: `src/artisanlib/canvas.py:203`, `src/artisanlib/canvas.py:252`, `src/artisanlib/canvas.py:17956`.
- Загрузка идет по цепочке `fileLoad()` -> `loadFile()` -> `deserialize()` -> `setProfile()`, а сохранение по цепочке `fileSave()` -> `getProfile()` -> `serialize()`: `src/artisanlib/main.py:13614-13658`, `src/artisanlib/main.py:15721-16434`, `src/artisanlib/main.py:17013-17348`.
- `ProfileData` в `src/artisanlib/atypes.py:128-240` показывает, что `.alog` смешивает raw roast data, events, extra channels, annotations, style/UI fields, alarms и computed summary, поэтому он плохо подходит как внутренний canonical format нового продукта.
- Для нового приложения наиболее обоснованная стратегия по коду Artisan: свой internal model + `.alog` compatibility layer минимум для import, а лучше для import/export отдельно от UI/render pipeline.
