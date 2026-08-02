from django.urls import path
from . import views

app_name = "pharmacy"

urlpatterns = [
    path("", views.PharmacyDashboardView.as_view(), name="dashboard"),
    path("unit/add/", views.add_measurement_unit, name="add_unit"),
    path("medicine/add/", views.add_medicine, name="add_medicine"),
    path("medicine/receive/", views.receive_medicine, name="receive_medicine"),
    path("medicine/dispense/", views.dispense_medicine, name="dispense_medicine"),
    path("medicine/dispense/<uuid:dispense_id>/confirm/", views.confirm_dispense, name="confirm_dispense"),
    path("medicine/dispense/<uuid:dispense_id>/cancel/", views.cancel_dispense, name="cancel_dispense"),
    path("batch/<uuid:batch_id>/price-update/", views.update_batch_price, name="update_batch_price"),
    path("batch/<uuid:batch_id>/export-history/", views.export_price_history_excel, name="export_price_history"),
]
