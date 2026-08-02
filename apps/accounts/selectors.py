"""Accounts selectors — barcha o'qish so'rovlari shu yerda."""
from __future__ import annotations

from typing import Optional

from django.db.models import Q, QuerySet

from apps.accounts.models import Role, User


def user_list(
    *,
    search: str = "",
    role_code: str = "",
    is_active: Optional[bool] = None,
) -> QuerySet[User]:
    """Xodimlar ro'yxati (qidiruv va filtrlar bilan)."""
    qs = User.objects.select_related("role").order_by("last_name", "first_name")
    if search:
        qs = qs.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(middle_name__icontains=search)
            | Q(phone__icontains=search)
        )
    if role_code:
        qs = qs.filter(role__code=role_code)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs


def role_list() -> QuerySet[Role]:
    """Barcha faol rollar."""
    return Role.objects.order_by("name")


def users_by_role(role_code: str) -> QuerySet[User]:
    """Berilgan roldagi faol xodimlar (masalan, barcha shifokorlar)."""
    return User.objects.filter(role__code=role_code, is_active=True).select_related("role")
