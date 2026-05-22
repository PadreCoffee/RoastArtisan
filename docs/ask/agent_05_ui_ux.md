# ASK-5 — UI / UX / screen map / role decomposition

**Объект:** Artisan / Roaster Scope (PyQt6, `src/artisanlib/main.py`, `canvas.py`, `uic/`)  
**Дата:** 2026-03-20  

---

## Executive summary

Интерфейс — **одно главное окно `ApplicationWindow`** с **встроенным графиком `tgraphcanvas` (matplotlib)** и **menu bar**, собираемым в коде (File / Edit / Roast / Config / Tools / View / Help). Сотни действий и диалогов разбросаны по **`main.py`** (тысячи строк) и модулям `artisanlib/*`; разметка частично из **`uic/`** (Qt Designer `.ui`). Критический операторский поток: **ON → START → фазы (CHARGE/…/DROP) → STOP/save** — кнопки и слоты в `main.py`, состояние и отрисовка в `canvas.py`. Логика **сильно срослась** с UI: `ApplicationWindow` держит устройства, настройки, plus-контроллер, ссылки на `qmc`, меню строятся процедурно со ссылками на `self.*Action`.

---

## Scope

Карта экранов/меню, перегруженные зоны, coupling UI↔логика, роли Novice/Roaster/Engineer, MVP-набор.

---

## UI map

### Главное окно

| Экран / подсистема UI | Где найдена | Для кого | MVP | Сложность отделения от архитектуры | Рекомендация |
|------------------------|-------------|----------|-----|-------------------------------------|--------------|
| Главное окно + график | `ApplicationWindow`, `tgraphcanvas` в `canvas.py` | Все | **Must** | Очень высокая | Новый UI-слой поверх **выделенного** session/sampler core |
| Меню **File** (New, Open recent, Import/Export, Reports, …) | `main.py` ~```4349:4370:src/artisanlib/main.py``` | Roaster + engineer | Must (open/save минимум) | Средняя | Сократить до Save/Load/Import в MVP |
| Меню **Roast** | `roast_menu` ~```4385:4396:src/artisanlib/main.py``` | Roaster | Must | Высокая | Вынести команды в **Application/Session** API |
| Меню **Config** (Machine, Themes, Temperature, Language, Mode) | ~```4397:4433:src/artisanlib/main.py``` | Engineer > Roaster | Themes/lang — nice; Machine — must для железа | Средняя–высокая | Разделить **Machine preset** vs **операторский** конфиг |
| Меню **Tools** (Analyzer, Convert temperature, …) | ~```4434:4447:src/artisanlib/main.py``` | Engineer / advanced | Optional | Средняя | За флаг «advanced» или отдельный режим |
| Меню **View** | ~```4453:4487:src/artisanlib/main.py``` | Все | Must (масштаб/панели) | Средняя | Упростить для novice |
| Меню **Help** + recent settings | ~```4488:4505:src/artisanlib/main.py``` | Все | Help минимальный | Низкая | Онбординг вместо длинного меню |
| Диалоги конфигурации портов/Modbus/S7/WS | триггеры из Config / machine | Engineer | Если целевой сегмент промышленный | Высокая | Мастер «подключения» вместо 20 диалогов |
| Plus / cloud UI | интеграция в `main.py` + `plus/*` | Roaster + business | Продуктовое решение | Средняя (модуль plus) | MVP без cloud или усечённый sync |
| Serial log окно | `serialLogDlg`, `serialAction` | Engineer | Debug | Средняя | Отдельный инструмент / скрытый режим |

### Подсистемы виджетов

- **`uic/`** — `.ui` файлы для частей интерфейса (точная карта — похоже на сотни файлов; углубление: inventory glob).
- **Кнопки ON/START и фазы** — связаны с `qmc.ToggleMonitor` / `ToggleRecorder` / `mark*` (см. ASK-1).

---

## Critical operator workflow

1. Выбор/настройка машины (Config / Machine, `.aset`).
2. **Monitor ON** — поток опроса, визуализация.
3. **START** — запись в буферы профиля.
4. Маркеры **CHARGE / FC / DROP** (кнопки/горячие клавиши в `main.py`).
5. **STOP** — останов записи, при необходимости autosave.
6. **Save / Export** — файловые операции из меню File.

Без этих шагов продукт не закрывает базовый сценарий обжарщика.

---

## Overloaded areas

- **`main.py`** — god-window: меню, устройства, Plus, диалоги, бизнес-правила.
- **Config / Machine** — пересечение пресетов, сетевых хостов, портов (см. длинные ветвления machine setup в `main.py`).
- **Report / Ranking / Production** — мощные функции, не нужные узкому MVP.
- **Analyzer / Tools** — вторично для ежедневной обжарки.

---

## UI / business logic coupling

| Зона | Проявление |
|------|------------|
| Сэмплинг | `SampleThread` → сигнал → `sample_processing` в графике (Qt) |
| Устройства | `ApplicationWindow.ser/modbus/...` создаются в конструкторе окна |
| Профиль | `getProfile`/`setProfile` на том же классе, что и меню |
| События | `eventactionx`, кнопки extradevices в `canvas`/`main` |

**Вывод:** «тонкого» ViewModel слоя нет; рефактор под новый UI потребует **вынос сессии и I/O** из `ApplicationWindow`.

---

## Role-based redesign recommendations

| Роль | Показывать в UI | Скрыть / advanced |
|------|-----------------|---------------------|
| **Novice** | ON/START, базовый график, CHARGE/DROP, Save | Modbus регистры, serial log, analyzer, convert menus |
| **Roaster** | Все фазы, события, alarms (ограниченно), экспорт | Низкоуровневые драйверы, internal diagnostics |
| **Engineer** | Machine presets, порты, extra devices, serial log, тест симулятора | Можно оставить как отдельный «режим» или CLI |

---

## MVP screen set (предложение)

1. **Dashboard** — график ET/BT (+ RoR), статус соединения, ON/START/STOP.
2. **Session summary** — метаданные партии, простая таблица событий.
3. **Save/Load** — файловый диалог + последние файлы.
4. **Settings (минимум)** — sample interval, единицы, один machine preset.
5. **Connect (wizard)** — один поток для serial **или** Modbus TCP вместо полного дерева Artisan.

---

## Key files

- `src/artisanlib/main.py` — меню, `ApplicationWindow`, интеграция Plus/устройств.
- `src/artisanlib/canvas.py` — график, сэмплинг-хуки, маркеры фаз.
- `src/artisanlib/uic/*.ui` — фрагменты форм (инвентаризация — отдельно).

---

## Confirmed conclusions

- Верхнее меню собирается в `main.py` с явными `QMenu` для File/Roast/Config/… — см. ```4349:4538:src/artisanlib/main.py```.

---

## Uncertain / requires deeper check

- Полный список `.ui` и соответствие экранам.
- Карта горячих клавиш (grep `QShortcut`).

---

## Reuse / redesign / rewrite

- **Reuse:** структура меню как чеклист функциональности для конкурентного анализа.
- **Redesign:** режимы Novice/Pro; wizard подключения.
- **Rewrite:** не тащить монолит `main.py` как основу нового UI.

---

## Open questions

- Нужен ли **полноэкранный** kiosk-режим для производства?
- Целевая платформа: только desktop или web-пульт поверх того же core?
