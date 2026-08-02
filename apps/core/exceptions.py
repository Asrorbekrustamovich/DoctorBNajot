"""Domen xatolari va DRF exception handler."""
from __future__ import annotations

from typing import Any, Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as base_handler


class DomainError(Exception):
    """Biznes qoidasi buzilganda ko'tariladigan asosiy xato."""

    default_message = "Biznes qoidasi buzildi."

    def __init__(self, message: str | None = None, *, code: str = "domain_error") -> None:
        self.message = message or self.default_message
        self.code = code
        super().__init__(self.message)


class InsufficientStockError(DomainError):
    default_message = "Omborda yetarli qoldiq yo'q."


class InvalidTransitionError(DomainError):
    default_message = "Bu holatdan bunday o'tish mumkin emas."


class PermissionDeniedError(DomainError):
    default_message = "Bu amal uchun huquq yo'q."


def drf_exception_handler(exc: Exception, context: dict[str, Any]) -> Optional[Response]:
    """Domen va Django validatsiya xatolarini DRF javobiga aylantiradi."""
    if isinstance(exc, DomainError):
        exc = drf_exceptions.ValidationError({"detail": exc.message, "code": exc.code})
    elif isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        exc = drf_exceptions.ValidationError(detail)
    return base_handler(exc, context)
