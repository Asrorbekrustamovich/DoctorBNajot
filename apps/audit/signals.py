"""Autentifikatsiya hodisalarini audit jurnaliga yozish."""
from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver
from django.http import HttpRequest

from apps.audit.models import AuditLog
from apps.audit.services import log_action
from apps.core.middleware import get_client_ip, get_user_agent


@receiver(user_logged_in)
def on_user_logged_in(sender: Any, request: HttpRequest, user: Any, **kwargs: Any) -> None:
    log_action(action=AuditLog.Action.LOGIN, actor=user, model_name="accounts.user",
               object_id=str(user.pk), object_repr=str(user))


@receiver(user_logged_out)
def on_user_logged_out(sender: Any, request: HttpRequest, user: Any, **kwargs: Any) -> None:
    if user is None:
        return
    log_action(action=AuditLog.Action.LOGOUT, actor=user, model_name="accounts.user",
               object_id=str(user.pk), object_repr=str(user))


@receiver(user_login_failed)
def on_user_login_failed(sender: Any, credentials: dict[str, Any], request: HttpRequest | None = None, **kwargs: Any) -> None:
    AuditLog.objects.create(
        action=AuditLog.Action.LOGIN_FAILED,
        actor_display=str(credentials.get("username", ""))[:255],
        model_name="accounts.user",
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
