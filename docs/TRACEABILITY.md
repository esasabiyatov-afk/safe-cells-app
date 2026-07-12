# Трассировка требований

| Источник | Требование | Планируемые модули | Проверка / этап |
|---|---|---|---|
| ТЗ 2–3 | EXE, локальный Flask, свободный порт, Windows-логин | `runtime`, `config` | Этапы 1, 2, 12 |
| Архитектура 2–5 | Общие БД, `mode=ro`, короткая запись, `BEGIN IMMEDIATE`, без WAL | `app/db` | Этапы 1, 4–8; тесты read-only/lock |
| Архитектура 6 | Атомарность двух баз через `ATTACH` | `app/db/transactions.py`, services | Этапы 4, 6, 7, 8; rollback-тесты |
| Архитектура 7–8 | Backup API, 30 комплектов, контролируемое восстановление, потеря сети | `app/services/backups.py`, error handlers | Базовая пара после записи — этап 4; манифесты/восстановление — этап 11 |
| ТЗ 4 | free/normal/expiring/overdue и настраиваемый порог | `services/statuses.py` | Этап 2; граничные даты |
| ТЗ 5 | Точные размеры и 126 seed-строк | `db/seed.py`, `cells` | Этап 1; CSV-тесты |
| ТЗ 6–7 | Тарифы и включительный расчёт | `services/rental_calculator.py` | Этап 3; 1/30/31/90/91/180/181 |
| ТЗ 8–9 | Калькулятор и занятие ячейки | routes, `services/contracts.py` | Этапы 3–4; валидация/гонка |
| ТЗ 10 | DOCX и плейсхолдеры | `app/documents` | Этап 9; шаблонные тесты |
| ТЗ 11 | Продление и штрафная формула | `app/services/renewals.py`, `app/routes/renewals.py` | 20 тестов этапа 6; граничные даты; браузер |
| ТЗ 11–12 | Закрытие и атомарный архив | `app/services/closures.py`, `app/routes/closures.py` | 16 тестов этапа 7; rollback; браузер |
| ТЗ 11–12 | Закрытие и перенос в архив | `services/closures.py` | Этап 7; межбазовый rollback |
| ТЗ 12 | Рабочая и архивная модели | `app/db/schema` | Этап 1 и интеграционные тесты |
| ТЗ 13–14 | ПДн полностью скрыты | `services/contract_details.py`, private POST route, templates, JS | Этапы 2, 5; токен/API/HTML/XSS/очистка |
| ТЗ 15 | Разрешённое редактирование и аудит | `services/editing.py`, `log` | Этап 8; whitelist/audit |
| ТЗ 16 | Сетка, поиск, фильтры, счётчики | templates/static/routes | Этап 2; UI и ручное одобрение |
| ТЗ 17 | Невозможные переходы | service validators + DB constraints | Этапы 4, 6, 7; negative tests |
| ТЗ 18 | Не добавлять ячейки в этой версии | admin routes | Этап 10; отсутствие endpoint/UI |
| AGENTS 6 | Нет реальных ПДн, параметризованный SQL, секреты вне Git | все слои | Все этапы; log/SQL/.gitignore tests |
| MASTER 5 | Документы статуса, руководства, changelog, Git-коммиты | `docs/`, Git | Каждый этап |
