"""Thread-local request konteksti.

Audit va created_by/updated_by avtomatik to'ldirish uchun joriy request
(va undan user, IP, User-Agent) ni istalgan joydan olish imkonini beradi.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser
    from django.http import HttpRequest, HttpResponse

_locals = threading.local()


def get_current_request() -> Optional["HttpRequest"]:
    """Joriy HTTP request (bo'lmasa None — masalan, celery task ichida)."""
    return getattr(_locals, "request", None)


def get_current_user() -> Optional["AbstractBaseUser"]:
    """Joriy autentifikatsiyalangan user yoki None."""
    request = get_current_request()
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user
    return None


def get_client_ip(request: Optional["HttpRequest"] = None) -> Optional[str]:
    """Klient IP manzili (X-Forwarded-For hisobga olinadi)."""
    request = request or get_current_request()
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def get_user_agent(request: Optional["HttpRequest"] = None) -> str:
    """Klient qurilmasi (User-Agent) satri."""
    request = request or get_current_request()
    if request is None:
        return ""
    return request.META.get("HTTP_USER_AGENT", "")[:512]


class CurrentRequestMiddleware:
    """Har bir requestni thread-local ga joylaydi va so'ng tozalaydi."""

    def __init__(self, get_response: Callable) -> None:
        self.get_response = get_response

    def __call__(self, request: "HttpRequest") -> "HttpResponse":
        _locals.request = request
        try:
            return self.get_response(request)
        finally:
            _locals.request = None
