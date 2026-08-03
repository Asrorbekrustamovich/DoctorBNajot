from django.urls import path
from apps.accounts import staff_views as views

app_name = "staff"

urlpatterns = [
    # Xodimlar
    path("", views.staff_list, name="list"),
    path("create/", views.staff_create, name="create"),
    path("<uuid:user_id>/edit/", views.staff_edit, name="edit"),
    path("<uuid:user_id>/delete/", views.staff_delete, name="delete"),
    path("<uuid:user_id>/restore/", views.staff_restore, name="restore"),
    path("<uuid:user_id>/reset-password/", views.staff_reset_password, name="reset_password"),

    # Xizmatlar katalogi
    path("services/", views.services_list, name="services"),
    path("services/assign/", views.services_bulk_assign, name="services_bulk_assign"),
    path("services/create/", views.service_create, name="service_create"),
    path("services/<uuid:service_id>/edit/", views.service_edit, name="service_edit"),
    path("services/<uuid:service_id>/delete/", views.service_delete, name="service_delete"),
]
