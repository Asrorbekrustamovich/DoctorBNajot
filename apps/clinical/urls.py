from django.urls import path
from apps.clinical.views import VisitConsultationView
from apps.clinical import views

app_name = "clinical"

urlpatterns = [
    path("visit/<uuid:pk>/consultation/", VisitConsultationView.as_view(), name="consultation"),
    
    # YANGA MODAL TIZIMI:
    path("visit/<uuid:pk>/consultation/modal/", views.ConsultationModalView.as_view(), name="consultation_modal"),
    path("visit/<uuid:pk>/consultation/modal/save/", views.ConsultationSaveModalView.as_view(), name="consultation_save_modal"),
    path("visit/<uuid:pk>/consultation/assign-services/", views.AssignServicesAjaxView.as_view(), name="consultation_assign_services"),
    path("templates/", views.MyTemplatesPageView.as_view(), name="my_templates"),
    path("consultation/<uuid:pk>/report/", views.ConsultationReportView.as_view(), name="consultation_report"),
    path("patient/<uuid:patient_id>/summary/", views.PatientSummaryView.as_view(), name="patient_summary"),
    path("template/modal/save/", views.TemplateSaveModalView.as_view(), name="template_save_modal"),
    path("template/modal/<uuid:template_id>/update/", views.TemplateUpdateModalView.as_view(), name="template_update_modal"),
    path("template/modal/<uuid:template_id>/delete/", views.TemplateDeleteModalView.as_view(), name="template_delete_modal"),
    
    path("visit/<uuid:pk>/redirect/", views.visit_redirect_htmx, name="consultation_redirect"),

    # Tashxis shablonlari (har shifokor o'ziniki)
    path("visit/<uuid:pk>/template/save/", views.save_consultation_template, name="save_consultation_template"),
    path("template/<uuid:template_id>/delete/", views.delete_consultation_template, name="delete_consultation_template"),

    # Statsionar hujjatlashtirish (hamshira) + bemor imzosi
    path("inpatient/stay/<uuid:stay_id>/docs/", views.stay_documentation, name="stay_documentation"),
    path("inpatient/stay/<uuid:stay_id>/docs/add/", views.stay_checklist_add, name="stay_checklist_add"),
    path("inpatient/docs/item/<uuid:item_id>/toggle/", views.stay_checklist_toggle, name="stay_checklist_toggle"),
    path("inpatient/stay/<uuid:stay_id>/procedure/add/", views.stay_procedure_add, name="stay_procedure_add"),
    path("inpatient/stay/<uuid:stay_id>/signature/", views.stay_save_signature, name="stay_save_signature"),

    # Operatsiya bayonnomasi
    path("surgery/schedule/<uuid:schedule_id>/report/", views.surgery_report_save, name="surgery_report_save"),
    path("surgery/schedule/<uuid:schedule_id>/report/print/", views.SurgeryReportView.as_view(), name="surgery_report_print"),
    path("surgery/schedule/<uuid:schedule_id>/act/print/", views.SurgeryActView.as_view(), name="surgery_act_print"),
    
    # Inpatient
    path("inpatient/", views.InpatientDashboardView.as_view(), name="inpatient_dashboard"),
    path("inpatient/stay/<uuid:stay_id>/order-services/", views.order_inpatient_services, name="order_inpatient_services"),
    path("inpatient/bed/<uuid:bed_id>/assign/", views.assign_bed_htmx, name="assign_bed"),
    path("inpatient/visit/<uuid:visit_id>/admit/", views.admit_visit_htmx, name="admit_visit"),
    path("inpatient/visit/<uuid:visit_id>/add-companion/", views.add_companion_to_stay_htmx, name="add_companion_to_stay"),
    path("inpatient/stay/<uuid:stay_id>/discharge/", views.discharge_bed, name="discharge_bed"),
    path("inpatient/settings/", views.RoomsSettingsView.as_view(), name="rooms_settings"),
    path("inpatient/room/add/", views.add_room, name="add_room"),
    path("inpatient/room/<uuid:room_id>/delete/", views.delete_room, name="delete_room"),
    path("inpatient/room/<uuid:room_id>/edit/", views.edit_room, name="edit_room"),
    path("inpatient/bed/add/", views.add_bed, name="add_bed"),
    path("inpatient/bed/<uuid:bed_id>/update-price/", views.update_bed_price, name="update_bed_price"),
    
    # Service Catalog Settings
    path("service/settings/", views.service_settings, name="service_settings"),
    path("service/add/", views.add_service, name="add_service"),
    path("service/<uuid:service_id>/update-price/", views.update_service_price, name="update_service_price"),
    path("service/<uuid:service_id>/toggle/", views.toggle_service, name="toggle_service"),

    # Surgery Settings
    path("surgery/settings/", views.surgery_settings, name="surgery_settings"),
    path("surgery/type/add/", views.add_surgery_type, name="add_surgery_type"),
    path("surgery/type/<uuid:type_id>/update-price/", views.update_surgery_type_price, name="update_surgery_type_price"),
    path("surgery/type/<uuid:type_id>/toggle/", views.toggle_surgery_type, name="toggle_surgery_type"),

    # Autoclave Settings
    path("autoclave/settings/", views.autoclave_settings, name="autoclave_settings"),
    path("autoclave/item/add/", views.autoclave_add_item, name="autoclave_add_item"),
    path("autoclave/item/<uuid:item_id>/delete/", views.delete_surgical_item, name="delete_surgical_item"),

    # Autoclave Dashboard
    path("autoclave/", views.autoclave_dashboard, name="autoclave_dashboard"),
    path("autoclave/item/<uuid:item_id>/update-status/", views.update_item_status, name="update_item_status"),


    # Surgery
    path("surgery/", views.SurgeryDashboardView.as_view(), name="surgery_dashboard"),
    path("surgery/table/", views.surgery_dashboard_table, name="surgery_dashboard_table"),
    path("surgery/admin-list/", views.AdminSurgeryListView.as_view(), name="surgery_admin_list"),
    path("surgery/schedule/", views.schedule_surgery, name="schedule_surgery"),
    path("surgery/schedule/<uuid:schedule_id>/edit/", views.edit_surgery_schedule, name="edit_surgery_schedule"),
    path("surgery/schedule/<uuid:schedule_id>/update/", views.update_surgery_status, name="update_surgery_status"),

    # --- Operatsiya jarayoni (4 qadam) ---
    path("surgery/<uuid:schedule_id>/process/", views.surgery_process, name="surgery_process"),
    path("surgery/<uuid:schedule_id>/step/patient-prep/", views.surgery_patient_prep, name="surgery_patient_prep"),
    path("surgery/<uuid:schedule_id>/step/anesthesia/", views.surgery_step_anesthesia, name="surgery_step_anesthesia"),
    path("surgery/<uuid:schedule_id>/step/preparation/", views.surgery_step_preparation, name="surgery_step_preparation"),
    path("surgery/<uuid:schedule_id>/start-operation/", views.surgery_start_operation, name="surgery_start_operation"),
    path("surgery/<uuid:schedule_id>/finish-operation/", views.surgery_finish_operation, name="surgery_finish_operation"),
    path("surgery/<uuid:schedule_id>/vitals/add/", views.surgery_vitals_add, name="surgery_vitals_add"),
    path("surgery/<uuid:schedule_id>/nurse-usage/add/", views.surgery_nurse_usage_add, name="surgery_nurse_usage_add"),
    path("surgery/<uuid:schedule_id>/anesthesia-request/add/", views.anesthesia_request_add_item, name="anesthesia_request_add_item"),
    path("surgery/<uuid:schedule_id>/nurse-request/add/", views.nurse_request_add_item, name="nurse_request_add_item"),
    path("surgery/<uuid:schedule_id>/anesthesia-request/send/", views.anesthesia_request_send, name="anesthesia_request_send"),
    path("surgery/<uuid:schedule_id>/anesthesia-extra/add/", views.anesthesia_extra_add, name="anesthesia_extra_add"),
    path("anesthesia-item/<uuid:item_id>/return/", views.anesthesia_item_return, name="anesthesia_item_return"),
    path("nurse-item/<uuid:item_id>/return/", views.nurse_item_return, name="nurse_item_return"),
    path("surgery-item/<uuid:item_id>/mark/", views.surgery_item_mark, name="surgery_item_mark"),
    path("operating-rooms/", views.operating_rooms_overview, name="operating_rooms_overview"),
    path("operating-rooms/add/", views.add_operating_room, name="add_operating_room"),
    path("operating-rooms/<uuid:room_id>/edit/", views.edit_operating_room, name="edit_operating_room"),
    path("operating-rooms/<uuid:room_id>/delete/", views.delete_operating_room, name="delete_operating_room"),

    # Ambulator xonalar (faqat superadmin)
    path("ambulatory-rooms/", views.ambulatory_rooms_settings, name="ambulatory_rooms_settings"),
    path("ambulatory-rooms/add/", views.add_ambulatory_room, name="add_ambulatory_room"),
    path("ambulatory-rooms/<uuid:pk>/edit/", views.edit_ambulatory_room, name="edit_ambulatory_room"),
    path("ambulatory-rooms/<uuid:pk>/delete/", views.delete_ambulatory_room, name="delete_ambulatory_room"),
    path("surgery/<uuid:schedule_id>/postop-recommendations/", views.surgery_postop_recommendations, name="surgery_postop_recommendations"),
    path("document/<str:doc_type>/<uuid:obj_id>/lock/", views.document_lock, name="document_lock"),
    path("anesthesia-stock/", views.anesthesia_stock_page, name="anesthesia_stock_page"),
    path("anesthesia-stock/add/", views.anesthesia_stock_add, name="anesthesia_stock_add"),
    path("anesthesia-stock/<uuid:stock_id>/edit/", views.anesthesia_stock_edit, name="anesthesia_stock_edit"),
    path("anesthesia-stock/<uuid:stock_id>/package/add/", views.anesthesia_stock_package_add, name="anesthesia_stock_package_add"),
    path("anesthesia-stock/package/<uuid:package_id>/delete/", views.anesthesia_stock_package_delete, name="anesthesia_stock_package_delete"),
    
    # Surgery Protocols
    path("surgery/schedule/<uuid:schedule_id>/anesthesia-request/", views.anesthesia_request_create, name="anesthesia_request_create"),
    path("surgery/schedule/<uuid:schedule_id>/preop-eval/", views.preop_evaluation_save, name="preop_evaluation_save"),
    path("surgery/schedule/<uuid:schedule_id>/nurse-usage-add/", views.nurse_usage_add, name="nurse_usage_add"),

    # Sterilization
    path("sterilization/", views.SterilizationDashboardView.as_view(), name="sterilization_dashboard"),
    path("sterilization/add/", views.add_surgical_item, name="add_surgical_item"),
    path("sterilization/clean/<uuid:item_id>/", views.clean_surgical_item, name="clean_surgical_item"),
    # Mutaxassislar (UZI, EKG, Laba)
    path("examiner/dashboard/", views.ExaminerDashboardView.as_view(), name="examiner_dashboard"),
    path("examiner/order/<uuid:order_id>/perform/", views.ExaminerOrderPerformView.as_view(), name="examiner_order_perform"),
    path("visit/<uuid:visit_id>/referral/", views.service_referral, name="service_referral"),
    path("examiner/order/<uuid:order_id>/call/", views.ExaminerOrderCallView.as_view(), name="examiner_order_call"),
    path("examiner/order/<uuid:order_id>/accept/", views.ExaminerOrderAcceptView.as_view(), name="examiner_order_accept"),
    path("examiner/order/<uuid:order_id>/defer/", views.ExaminerOrderDeferView.as_view(), name="examiner_order_defer"),
]
