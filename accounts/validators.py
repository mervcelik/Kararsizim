from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

RESERVED_USERNAMES = frozenset(
    {"admin", "root", "api", "static", "anket", "giris", "kayit", "cikis", "kullanici", "hakkinda"}
)

username_format_validator = RegexValidator(
    regex=r"^[a-zA-Z0-9_]{3,20}$",
    message="Kullanıcı adı 3–20 karakter olmalı; sadece harf, rakam ve alt çizgi kullanabilirsin.",
    code="invalid_username",
)


def validate_not_reserved(value):
    if value.lower() in RESERVED_USERNAMES:
        raise ValidationError("Bu kullanıcı adı kullanılamaz.", code="reserved_username")
