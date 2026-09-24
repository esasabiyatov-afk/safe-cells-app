"""One catalog of template fields used by WhatsApp text and DOCX files.

The square-bracket names are the public syntax shown to administrators.
Older WhatsApp labels and double-brace DOCX names remain supported as
compatibility aliases, but are deliberately not advertised for new templates.
"""

from __future__ import annotations

import re


PATRONYMIC_MARKERS = frozenset({"уулу", "кызы"})


def client_greeting_name(full_name: str) -> str:
    """Build a polite greeting without assuming every client has a patronymic."""

    parts = full_name.split()
    if len(parts) <= 1:
        return " ".join(parts)
    for index, part in enumerate(parts):
        if part.casefold() not in PATRONYMIC_MARKERS:
            continue
        if index + 1 < len(parts):
            return parts[index + 1]
        return parts[0]
    if len(parts) == 2:
        return parts[1]
    return " ".join(parts[1:3])


DOCUMENT_PLACEHOLDER_RE = re.compile(
    r"\{\{(?P<legacy>[A-Z][A-Z0-9_]*)\}\}"
    r"|\[(?P<bank>[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z0-9_.]{0,79})\]"
)
MESSAGE_PLACEHOLDER_RE = re.compile(
    r"\{\{(?P<legacy>[A-Z][A-Z0-9_]*)\}\}"
    r"|\[(?P<bank>[^\[\]\r\n]{1,80})\]"
)


def _field(
    code: str,
    description: str,
    *,
    group: str,
    channels: tuple[str, ...],
) -> dict[str, object]:
    labels = {
        ("docx", "whatsapp"): "WhatsApp и DOCX",
        ("docx",): "Только DOCX",
        ("whatsapp",): "Только WhatsApp",
    }
    normalized_channels = tuple(sorted(channels))
    return {
        "code": f"[{code}]",
        "description": description,
        "group": group,
        "usage": labels[normalized_channels],
        "channels": list(normalized_channels),
    }


TEMPLATE_FIELD_DICTIONARY = (
    _field(
        "Клиент.Обращение",
        "Имя и отчество либо только имя по правилам банковского обращения.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Клиент.ФИО",
        "Полное ФИО клиента из договора.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Клиент.Телефон",
        "Телефон в том виде, как он записан в договоре.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Счет.Номер",
        "Номер счёта клиента из АБС.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Сейф.Номер",
        "Номер ячейки. В DOCX однозначный номер печатается с ведущим нулём.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Сейф.Размер",
        "Полный размер: высота×ширина×глубина мм.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Сейф.Высота",
        "Высота ячейки в миллиметрах.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Сейф.Ширина",
        "Ширина ячейки в миллиметрах.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Сейф.Глубина",
        "Глубина ячейки в миллиметрах.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Договор.Начало",
        "Дата начала аренды с месяцем прописью.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Договор.Конец",
        "Дата окончания аренды с месяцем прописью.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Договор.Срок",
        "Первоначальный срок договора в днях.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Договор.Сумма",
        "Первоначальная стоимость аренды цифрами.",
        group="Основные данные",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Договор.Статус",
        "Текущий статус аренды: «Истекает» или «Просрочено».",
        group="Основные данные",
        channels=("whatsapp",),
    ),
    _field(
        "Дата.Сегодня",
        "Дата формирования документа или напоминания на русском языке.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Дата.СегодняК",
        "Та же дата на кыргызском языке.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Клиент.Документ.Номер",
        "Серия и номер ID-карты.",
        group="Документ и договор",
        channels=("docx",),
    ),
    _field(
        "Клиент.Документ.Выдан",
        "Орган, выдавший ID-карту.",
        group="Документ и договор",
        channels=("docx",),
    ),
    _field(
        "Клиент.Документ.ДатаВыдачи",
        "Дата выдачи ID-карты.",
        group="Документ и договор",
        channels=("docx",),
    ),
    _field(
        "Система.Пользователь",
        "Сотрудник-исполнитель, выбранный для документа; в WhatsApp — текущий сотрудник.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Договор.НачалоК",
        "Дата начала договора на кыргызском языке.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Договор.КонецК",
        "Дата окончания договора на кыргызском языке.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Договор.НачалоД",
        "Дата начала в кавычках на русском языке.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Договор.НачалоДК",
        "Дата начала в кавычках на кыргызском языке без окончания «-жылдагы».",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Сумма",
        "Первоначальная стоимость аренды цифрами; старое имя поля документов.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Залог.Сумма",
        "Сумма залога цифрами.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Залог.Цифр",
        "Сумма залога цифрами; старое имя поля документов.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Залог.Пропись",
        "Сумма залога прописью на русском языке.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Залог.ПрописьК",
        "Сумма залога прописью на кыргызском языке.",
        group="Документ и договор",
        channels=("whatsapp", "docx"),
    ),
    _field(
        "Продление.Начало",
        "Дата начала конкретного продления на русском языке.",
        group="Только для продления",
        channels=("docx",),
    ),
    _field(
        "Продление.Конец",
        "Дата окончания конкретного продления на русском языке.",
        group="Только для продления",
        channels=("docx",),
    ),
    _field(
        "Продление.НачалоК",
        "Дата начала конкретного продления на кыргызском языке.",
        group="Только для продления",
        channels=("docx",),
    ),
    _field(
        "Продление.КонецК",
        "Дата окончания конкретного продления на кыргызском языке.",
        group="Только для продления",
        channels=("docx",),
    ),
    _field(
        "Продление.Сумма",
        "Стоимость конкретного продления цифрами.",
        group="Только для продления",
        channels=("docx",),
    ),
    _field(
        "Продление.Срок",
        "Срок конкретного продления в днях.",
        group="Только для продления",
        channels=("docx",),
    ),
)


PUBLIC_DOCUMENT_PLACEHOLDERS = frozenset(
    str(item["code"])[1:-1]
    for item in TEMPLATE_FIELD_DICTIONARY
    if "docx" in item["channels"]
)
PUBLIC_REMINDER_PLACEHOLDERS = frozenset(
    str(item["code"])
    for item in TEMPLATE_FIELD_DICTIONARY
    if "whatsapp" in item["channels"]
)

# Old names remain valid so saved texts and uploaded files keep working.
LEGACY_DOCUMENT_PLACEHOLDERS = frozenset(
    {
        "CLIENT_FULL_NAME",
        "ID_CARD_NUMBER",
        "ID_CARD_ISSUER",
        "ID_CARD_ISSUE_DATE",
        "ACCOUNT_NUMBER",
        "SAFE_NUMBER",
        "SAFE_HEIGHT",
        "SAFE_WIDTH",
        "SAFE_DEPTH",
        "START_DATE",
        "END_DATE",
        "RENT_DAYS",
        "RENT_PRICE",
        "CREATION_DATE",
        "EMPLOYEE",
    }
)
LEGACY_REMINDER_ALIASES = frozenset(
    {
        "[Обращение]",
        "[Имя]",
        "[ФИО клиента]",
        "[Номер ячейки]",
        "[Размер ячейки]",
        "[Дата начала]",
        "[Дата окончания]",
        "[Количество дней]",
        "[Телефон]",
        "[Номер счёта]",
        "[Статус аренды]",
    }
)
LEGACY_REMINDER_DOCUMENT_PLACEHOLDERS = frozenset(
    {
        "CLIENT_FULL_NAME",
        "ACCOUNT_NUMBER",
        "SAFE_NUMBER",
        "SAFE_HEIGHT",
        "SAFE_WIDTH",
        "SAFE_DEPTH",
        "START_DATE",
        "END_DATE",
        "RENT_DAYS",
        "RENT_PRICE",
        "CREATION_DATE",
        "EMPLOYEE",
    }
)

ALLOWED_DOCUMENT_PLACEHOLDERS = (
    PUBLIC_DOCUMENT_PLACEHOLDERS | LEGACY_DOCUMENT_PLACEHOLDERS
)
ALLOWED_REMINDER_PLACEHOLDERS = (
    PUBLIC_REMINDER_PLACEHOLDERS
    | LEGACY_REMINDER_ALIASES
    | frozenset(
        f"{{{{{name}}}}}"
        for name in LEGACY_REMINDER_DOCUMENT_PLACEHOLDERS
    )
)

RENEWAL_DOCUMENT_PLACEHOLDERS = frozenset(
    {
        "Продление.Начало",
        "Продление.Конец",
        "Продление.НачалоК",
        "Продление.КонецК",
        "Продление.Сумма",
        "Продление.Срок",
    }
)


def invalid_document_placeholders(
    placeholders: set[str] | frozenset[str],
    *,
    document_type: str,
) -> set[str]:
    """Return fields that have no value for the selected document event."""

    if document_type == "renewal":
        return set()
    return set(placeholders) & RENEWAL_DOCUMENT_PLACEHOLDERS
