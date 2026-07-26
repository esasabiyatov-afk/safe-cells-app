# Трассировка требований

| Источник | Требование | Модули | Проверка / этап |
|---|---|---|---|
| ТЗ 2–3, D-044, D-063–D-064 | Переносимый GUI EXE, локальный Flask на свободном loopback-порту, ярлык, жизненный цикл вкладок, общий справочник и обязательный локальный выбор сотрудника | `app/runtime.py`, `app/routes/system.py`, `app/static/js/runtime.js`, `safe-cells.spec`, `scripts/`, `services/employee.py` | Этап 12; 8 runtime-тестов, три экземпляра, изолированный EXE и браузер |
| Архитектура 2–5 | Общие БД, `mode=ro`, короткая запись, `BEGIN IMMEDIATE`, без WAL | `app/db` | Этапы 1, 4–8; тесты read-only/lock |
| Архитектура 6 | Атомарность двух баз через `ATTACH` | `app/db/connections.py`, сервисы записи | Этапы 4, 6, 7, 8; rollback-тесты |
| Архитектура 7–8 | Backup API, 30 комплектов, контролируемое восстановление, потеря сети | `app/services/backups.py`, `app/services/instances.py`, admin routes/UI | Этап 11: 17 профильных тестов, полный `pytest`, браузерное повреждение/восстановление |
| ТЗ 4 | free/normal/expiring/overdue и настраиваемый порог | `services/statuses.py` | Этап 2; граничные даты |
| ТЗ 5 | Точные размеры и 126 seed-строк | `db/seed.py`, `cells` | Этап 1; CSV-тесты |
| ТЗ 6–7 | Тарифы и включительный расчёт | `services/rental_calculator.py` | Этап 3; 1/30/31/90/91/180/181 |
| ТЗ 8–9 | Калькулятор и занятие ячейки | routes, `services/contracts.py` | Этапы 3–4; валидация/гонка |
| ТЗ 10 | DOCX и плейсхолдеры | `app/documents` | Этап 9; шаблонные тесты |
| ТЗ 11 | Продление и штрафная формула | `app/services/renewals.py`, `app/routes/renewals.py` | 23 теста этапа 6; граничные даты; браузер |
| ТЗ 11–12 | Закрытие и атомарный архив | `app/services/closures.py`, `app/routes/closures.py` | 18 тестов этапа 7; межбазовый rollback; браузер |
| ТЗ 12 | Рабочая и архивная модели | `app/db/schema` | Этап 1 и интеграционные тесты |
| ТЗ 13–14, D-025, D-028 | На сетке разрешены фамилия и инициалы; полное ФИО загружается при открытии одной карточки; остальные ПДн скрыты | `services/cells.py`, `services/contract_details.py`, private POST routes, templates, JS | Этапы 2, 5; whitelist общего API, токен/API/HTML/XSS/очистка |
| ТЗ 15, D-030 | Разрешённое редактирование и аудит | `services/editing.py`, `routes/editing.py`, `log`, UI | Этап 8; whitelist/audit/API/browser |
| ТЗ 12, 15, D-053–D-060 | Отдельная вкладка общего журнала с ФИО и XLSX-выпиской, особая занятость и импорт заявления АБС | `services/journal.py`, `services/journal_reports.py`, `services/cell_blocks.py`, `services/statement_import.py`, routes/templates/static | Этап 11.5; 17 тестов журнала, 8 особой занятости, 13 импорта заявления, API и браузер |
| ТЗ 16 | Сетка, поиск, фильтры, счётчики | templates/static/routes | Этап 2; UI и ручное одобрение |
| Требование 26.07.2026, D-078 | WhatsApp-напоминание только для истекающей/просроченной аренды, телефон, точное время и счётчик конкретного договора | `services/reminders.py`, `services/phone_numbers.py`, reminder route, schema/migration 5→6, templates/static | 9 профильных тестов, миграция/rollback, полный `pytest`, portable smoke |
| ТЗ 17 | Невозможные переходы | service validators + DB constraints | Этапы 4, 6, 7; negative tests |
| ТЗ 18 | Не добавлять ячейки в этой версии | admin routes | Этап 10; отсутствие endpoint/UI |
| AGENTS 6 | Нет реальных ПДн, параметризованный SQL, секреты вне Git | все слои | Все этапы; log/SQL/.gitignore tests |
| MASTER 5 | Документы статуса, руководства, changelog, Git-коммиты | `docs/`, Git | Каждый этап |
