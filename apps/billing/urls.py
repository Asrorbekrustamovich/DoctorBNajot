from django.urls import path
from . import views, reports

app_name = "billing"

urlpatterns = [
    path("", views.BillingDashboardView.as_view(), name="dashboard"),
    path("visit/<uuid:visit_id>/", views.view_invoice, name="view_invoice"),
    path("patient/<uuid:patient_id>/invoices/", views.patient_invoices, name="patient_invoices"),
    path("invoice/<uuid:invoice_id>/pay/", views.pay_invoice, name="pay_invoice"),
    path("invoice/<uuid:invoice_id>/refund/", views.refund_invoice, name="refund_invoice"),
    path("order/<uuid:order_id>/cancel/", views.cancel_service_order, name="cancel_service_order"),
    path("dispense/<uuid:dispense_id>/return/", views.return_medicine, name="return_medicine"),
    path("dispense/<uuid:dispense_id>/edit-quantity/", views.edit_medicine_quantity, name="edit_medicine_quantity"),
    path("stay/<uuid:stay_id>/edit-days/", views.edit_inpatient_days, name="edit_inpatient_days"),
    path("stay/<uuid:stay_id>/cancel/", views.cancel_inpatient_stay, name="cancel_inpatient_stay"),
    path("consultation/<uuid:cons_id>/edit-fee/", views.edit_consultation_fee, name="edit_consultation_fee"),

    # Direktor: hisobot va shifokor qabul narxlari
    path("registrator/", views.registrator_payments, name="registrator_payments"),
    path("surgery/<uuid:surgery_id>/edit-price/", views.edit_surgery_price, name="edit_surgery_price"),
    path("surgery/<uuid:surgery_id>/cancel/", views.cancel_surgery, name="cancel_surgery"),
    path("report/", reports.RevenueReportView.as_view(), name="revenue_report"),
    path("report/excel/", reports.revenue_excel, name="revenue_excel"),
    path("prices/", reports.doctor_prices, name="doctor_prices"),
    path("statistics/", views.SuperadminStatisticsView.as_view(), name="superadmin_statistics"),
]
