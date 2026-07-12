"""Approved formatting rules for bank DOCX placeholder values."""

from __future__ import annotations

from datetime import date


RU_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
KY_MONTHS = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)


def format_russian_date(value: date) -> str:
    return f"{value.day} {RU_MONTHS[value.month - 1]} {value.year} г."


def format_kyrgyz_date(value: date) -> str:
    return f"{value.day}-{KY_MONTHS[value.month - 1]} {value.year}-ж."


def format_document_issue_date(value: date) -> str:
    return value.strftime("%d.%m.%Y-ж/г.")


RU_ONES = ("", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
RU_TEENS = ("десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать")
RU_TENS = ("", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто")
RU_HUNDREDS = ("", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот")


def _ru_triplet(number: int, *, feminine: bool = False) -> list[str]:
    words = [RU_HUNDREDS[number // 100]] if number // 100 else []
    remainder = number % 100
    if 10 <= remainder <= 19:
        words.append(RU_TEENS[remainder - 10])
        return words
    if remainder // 10:
        words.append(RU_TENS[remainder // 10])
    one = remainder % 10
    if one:
        if feminine and one in (1, 2):
            words.append("одна" if one == 1 else "две")
        else:
            words.append(RU_ONES[one])
    return words


def _ru_form(number: int, forms: tuple[str, str, str]) -> str:
    last_two = number % 100
    if 11 <= last_two <= 19:
        return forms[2]
    last = number % 10
    return forms[0] if last == 1 else forms[1] if 2 <= last <= 4 else forms[2]


def amount_in_words_ru(number: int) -> str:
    if not isinstance(number, int) or isinstance(number, bool) or not 0 <= number < 1_000_000_000:
        raise ValueError("Сумма для записи прописью должна быть от 0 до 999999999.")
    if number == 0:
        return "Ноль"
    words: list[str] = []
    millions = number // 1_000_000
    thousands = number // 1_000 % 1_000
    units = number % 1_000
    if millions:
        words.extend(_ru_triplet(millions))
        words.append(_ru_form(millions, ("миллион", "миллиона", "миллионов")))
    if thousands:
        words.extend(_ru_triplet(thousands, feminine=True))
        words.append(_ru_form(thousands, ("тысяча", "тысячи", "тысяч")))
    words.extend(_ru_triplet(units))
    return " ".join(words).capitalize()


KY_ONES = ("", "бир", "эки", "үч", "төрт", "беш", "алты", "жети", "сегиз", "тогуз")
KY_TENS = ("", "он", "жыйырма", "отуз", "кырк", "элүү", "алтымыш", "жетимиш", "сексен", "токсон")


def _ky_under_thousand(number: int) -> list[str]:
    words: list[str] = []
    if number // 100:
        words.extend((KY_ONES[number // 100], "жүз"))
    remainder = number % 100
    if remainder // 10:
        words.append(KY_TENS[remainder // 10])
    if remainder % 10:
        words.append(KY_ONES[remainder % 10])
    return words


def amount_in_words_ky(number: int) -> str:
    if not isinstance(number, int) or isinstance(number, bool) or not 0 <= number < 1_000_000_000:
        raise ValueError("Сумма үчүн уруксат берилген чек 0–999999999.")
    if number == 0:
        return "Нөл"
    words: list[str] = []
    for divisor, label in ((1_000_000, "миллион"), (1_000, "миң")):
        part = number // divisor % 1_000
        if part:
            words.extend(_ky_under_thousand(part))
            words.append(label)
    words.extend(_ky_under_thousand(number % 1_000))
    return " ".join(words).capitalize()
