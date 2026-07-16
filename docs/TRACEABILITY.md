# Трассировка требований

| Источник | Требование | Планируемые модули | Проверка / этап |
|---|---|---|---|
| ТЗ 2–3 и D-044 | EXE, локальный Flask, свободный порт, общий справочник и обязательный локальный выбор сотрудника | `runtime`, `config`, `services/employee.py` | Этапы 1, 2, 10, 12 |
| Архитектура 2–5 | Общие БД, `mode=ro`, короткая запись, `BEGIN IMMEDIATE`, без WAL | `app/db` | Этапы 1, 4–8; тесты read-only/lock |
| Архитектура 6 | Атомарность двух баз через `ATTACH` | `app/db/transactions.py`, services | Этапы 4, 6, 7, 8; rollback-тесты |
| Архитектура 7–8 | Backup API, 30 комплектов, контролируемое восстановление, потеря сети | `app/services/backups.py`, `app/services/instances.py`, admin routes/UI | Этап 11: 15 профильных тестов, полный `pytest`, браузерное повреждение/восстановление |
| ТЗ 4 | free/normal/expiring/overdue и настраиваемый порог | `services/statuses.py` | Этап 2; граничные даты |
| ТЗ 5 | Точные размеры и 126 seed-строк | `db/seed.py`, `cells` | Этап 1; CSV-тесты |
| ТЗ 6–7 | Тарифы и включительный расчёт | `services/rental_calculator.py` | Этап 3; 1/30/31/90/91/180/181 |
| ТЗ 8–9 | Калькулятор и занятие ячейки | routes, `services/contracts.py` | Этапы 3–4; валидация/гонка |
| ТЗ 10 | DOCX и плейсхолдеры | `app/documents` | Этап 9; шаблонные тесты |
| ТЗ 11 | Продление и штрафная формула | `app/services/renewals.py`, `app/routes/renewals.py` | 20 тестов этапа 6; граничные даты; браузер |
| ТЗ 11–12 | Закрытие и атомарный архив | `app/services/closures.py`, `app/routes/closures.py` | 16 тестов этапа 7; rollback; браузер |
| ТЗ 11–12 | Закрытие и перенос в архив | `services/closures.py` | Этап 7; межбазовый rollback |
| ТЗ 12 | Рабочая и архивная модели | `app/db/schema` | Этап 1 и интеграционные тесты |
| ТЗ 13–14, D-025, D-028 | На сетке разрешены фамилия и инициалы; полное ФИО загружается при открытии одной карточки; остальные ПДн скрыты | `services/cells.py`, `services/contract_details.py`, private POST routes, templates, JS | Этапы 2, 5; whitelist общего API, токен/API/HTML/XSS/очистка |
| ТЗ 15, D-030 | Разрешённое редактирование и аудит | `services/editing.py`, `routes/editing.py`, `log`, UI | Этап 8; whitelist/audit/API/browser |
| ТЗ 12, 15, D-052 и D-053 | Общий журнал занятия/продления/закрытия с ФИО и XLSX-выпиской | `services/journal.py`, `services/journal_reports.py`, `routes/journal.py`, `static/js/journal.js` | Этап 11.5; активный/архивный клиент, исключение исправлений и секретных реквизитов, фильтры/пагинация/XLSX/API/browser |
| ТЗ 16 | Сетка, поиск, фильтры, счётчики | templates/static/routes | Этап 2; UI и ручное одобрение |
| ТЗ 17 | Невозможные переходы | service validators + DB constraints | Этапы 4, 6, 7; negative tests |
| ТЗ 18 | Не добавлять ячейки в этой версии | admin routes | Этап 10; отсутствие endpoint/UI |
| AGENTS 6 | Нет реальных ПДн, параметризованный SQL, секреты вне Git | все слои | Все этапы; log/SQL/.gitignore tests |
| MASTER 5 | Документы статуса, руководства, changelog, Git-коммиты | `docs/`, Git | Каждый этап |
