"""Validation and normalization of client phone numbers for WhatsApp."""

from __future__ import annotations


class PhoneNumberValidationError(ValueError):
    """A phone number cannot be used in an international WhatsApp link."""


def normalize_whatsapp_phone(value: object) -> str:
    """Return an international phone number containing ASCII digits only."""

    if not isinstance(value, str) or not value.strip():
        raise PhoneNumberValidationError(
            "У клиента не указан номер телефона. Добавьте номер в данных договора."
        )
    normalized = value.strip()
    if any(
        not (character.isascii() and character.isdigit())
        and not character.isspace()
        and character not in "+()-"
        for character in normalized
    ):
        raise PhoneNumberValidationError(
            "Номер телефона содержит недопустимые символы."
        )
    digits = "".join(
        character
        for character in normalized
        if character.isascii() and character.isdigit()
    )
    if not 7 <= len(digits) <= 15 or digits.startswith("0"):
        raise PhoneNumberValidationError(
            "Укажите корректный номер телефона в международном формате, "
            "например +996 (555) 123-456."
        )
    return digits
