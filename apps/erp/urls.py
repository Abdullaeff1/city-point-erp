from django.urls import path
from django.views.generic import RedirectView

from apps.erp import (
    announcement_views,
    building_procedure_views,
    crm_views,
    drawing_views,
    resident_views,
    views,
)
from apps.erp.work_orders import (
    WorkOrderDetailView,
    WorkOrderImportView,
    WorkOrderListView,
    WorkOrderSheetTemplateView,
)

app_name = "erp"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("people-inside/", views.PeopleInsideView.as_view(), name="people_inside"),
    path("people-inside/export.xlsx", views.PeopleInsideExportView.as_view(), name="people_inside_export"),
    path("people-inside/<int:pk>/", views.PeopleInsideDetailView.as_view(), name="people_inside_detail"),
    path("reception/", views.ReceptionView.as_view(), name="reception"),
    path("reception/<int:pk>/status/", views.ReceptionStatusView.as_view(), name="reception_status"),
    path(
        "reception/overdue/checkout/",
        views.ReceptionOverdueCheckoutView.as_view(),
        name="reception_overdue_checkout",
    ),
    path("reception/<int:pk>/update/", views.ReceptionVisitUpdateView.as_view(), name="reception_visit_update"),
    path(
        "reception/guest-list/template/",
        views.ReceptionGuestListTemplateView.as_view(),
        name="reception_guest_list_template",
    ),
    path(
        "reception/guest-list/preview/",
        views.ReceptionGuestListPreviewView.as_view(),
        name="reception_guest_list_preview",
    ),
    path(
        "reception/guest-list/confirm/",
        views.ReceptionGuestListConfirmView.as_view(),
        name="reception_guest_list_confirm",
    ),
    path(
        "reception/guest-list/<int:pk>/check-in/",
        views.ReceptionGuestListCheckInView.as_view(),
        name="reception_guest_list_check_in",
    ),
    path("reception/guest-lookup/", views.ReceptionGuestLookupView.as_view(), name="reception_guest_lookup"),
    path("reception/export/", views.ReceptionExportView.as_view(), name="reception_export"),
    path("alerts/", views.NotificationListView.as_view(), name="alerts"),
    path("tickets/", views.TicketListView.as_view(), name="tickets"),
    path("tickets/new/", views.TicketCreateView.as_view(), name="ticket_create"),
    path("tickets/<str:code>/", views.TicketDetailView.as_view(), name="ticket_detail"),
    path("spaces/", views.SpaceListView.as_view(), name="spaces"),
    path("spaces/new/", views.SpaceCreateView.as_view(), name="space_create"),
    path("floors/new/", views.FloorCreateView.as_view(), name="floor_create"),
    path(
        "building-assets/",
        RedirectView.as_view(pattern_name="erp:building_equipment", permanent=False),
        name="building_assets",
    ),
    path(
        "building-equipment/",
        views.BuildingEquipmentListView.as_view(),
        name="building_equipment",
    ),
    path(
        "building-inventory/",
        views.BuildingInventoryListView.as_view(),
        name="building_inventory",
    ),
    path("spaces/<str:code>/edit/", views.SpaceUpdateView.as_view(), name="space_edit"),
    path("spaces/<str:code>/delete/", views.SpaceDeleteView.as_view(), name="space_delete"),
    path("spaces/<str:code>/", views.SpaceDetailView.as_view(), name="space_detail"),
    path(
        "spaces/<str:code>/drawings/upload/",
        drawing_views.SpaceDrawingUploadView.as_view(),
        name="space_drawing_upload",
    ),
    path(
        "drawings/<int:pk>/download/",
        drawing_views.SpaceDrawingDownloadView.as_view(),
        name="space_drawing_download",
    ),
    path(
        "drawings/<int:pk>/svg/",
        drawing_views.SpaceDrawingSvgView.as_view(),
        name="space_drawing_svg",
    ),
    path(
        "drawings/<int:pk>/png/",
        drawing_views.SpaceDrawingPngPreviewView.as_view(),
        name="space_drawing_png",
    ),
    path(
        "drawing-access/",
        drawing_views.DrawingAccessQueueView.as_view(),
        name="drawing_access_queue",
    ),
    path(
        "drawing-access/<int:pk>/decide/",
        drawing_views.DrawingAccessDecideView.as_view(),
        name="drawing_access_decide",
    ),
    path("residents/", views.ResidentListView.as_view(), name="residents"),
    path("residents/new/", resident_views.ResidentCreateView.as_view(), name="resident_create"),
    path("residents/<slug:slug>/", views.ResidentDetailView.as_view(), name="resident_detail"),
    path(
        "residents/<slug:slug>/edit/",
        resident_views.ResidentUpdateView.as_view(),
        name="resident_edit",
    ),
    path(
        "residents/<slug:slug>/archive/",
        resident_views.ResidentArchiveView.as_view(),
        name="resident_archive",
    ),
    path(
        "residents/<slug:slug>/unarchive/",
        resident_views.ResidentUnarchiveView.as_view(),
        name="resident_unarchive",
    ),
    path(
        "residents/<slug:slug>/documents/",
        resident_views.ResidentDocumentsView.as_view(),
        name="resident_documents",
    ),
    path(
        "residents/<slug:slug>/documents/new/",
        resident_views.ResidentDocumentCreateView.as_view(),
        name="resident_document_create",
    ),
    path(
        "residents/<slug:slug>/documents/<int:pk>/edit/",
        resident_views.ResidentDocumentUpdateView.as_view(),
        name="resident_document_edit",
    ),
    path(
        "residents/<slug:slug>/documents/<int:pk>/delete/",
        resident_views.ResidentDocumentDeleteView.as_view(),
        name="resident_document_delete",
    ),
    path(
        "residents/<slug:slug>/documents/<int:pk>/download/",
        resident_views.ResidentDocumentDownloadView.as_view(),
        name="resident_document_download",
    ),
    path(
        "residents/<slug:slug>/tickets/",
        views.ResidentTicketsView.as_view(),
        name="resident_tickets",
    ),
    path(
        "residents/<slug:slug>/guests/",
        views.ResidentGuestsView.as_view(),
        name="resident_guests",
    ),
    path(
        "residents/<slug:slug>/employees/",
        views.ResidentEmployeesAccessView.as_view(),
        name="resident_employees",
    ),
    path(
        "residents/<slug:slug>/employees/export/",
        views.ResidentAccessExportView.as_view(),
        name="resident_access_export",
    ),
    path(
        "residents/<slug:slug>/employees/<int:pk>/",
        views.ResidentEmployeeAccessDetailView.as_view(),
        name="resident_employee_access",
    ),
    path(
        "residents/<slug:slug>/employees/<int:pk>/export/",
        views.ResidentAccessExportView.as_view(),
        name="resident_employee_access_export",
    ),
    path("internal-staff/access/", views.InternalStaffAccessView.as_view(), name="internal_staff_access"),
    path(
        "internal-staff/access/export/",
        views.InternalStaffAccessExportView.as_view(),
        name="internal_staff_access_export",
    ),
    path(
        "internal-staff/access/<int:pk>/",
        views.InternalStaffAccessDetailView.as_view(),
        name="internal_staff_access_detail",
    ),
    path(
        "internal-staff/access/<int:pk>/export/",
        views.InternalStaffAccessExportView.as_view(),
        name="internal_staff_employee_export",
    ),
    path("leases/", views.LeaseListView.as_view(), name="leases"),
    path("leases/<str:code>/", views.LeaseDetailView.as_view(), name="lease_detail"),
    path("crm/leads/", crm_views.CrmLeadListView.as_view(), name="crm_leads"),
    path("crm/leads/<int:pk>/", crm_views.CrmLeadDetailView.as_view(), name="crm_lead_detail"),
    path("crm/opportunities/", crm_views.CrmOpportunityListView.as_view(), name="crm_opportunities"),
    path(
        "crm/opportunities/<int:pk>/",
        crm_views.CrmOpportunityDetailView.as_view(),
        name="crm_opportunity_detail",
    ),
    path("crm/offers/", crm_views.CrmOfferListView.as_view(), name="crm_offers"),
    path("crm/offers/<int:pk>/", crm_views.CrmOfferDetailView.as_view(), name="crm_offer_detail"),
    path(
        "crm/lease-applications/",
        crm_views.CrmLeaseApplicationListView.as_view(),
        name="crm_lease_applications",
    ),
    path(
        "crm/lease-applications/<int:pk>/",
        crm_views.CrmLeaseApplicationDetailView.as_view(),
        name="crm_lease_application_detail",
    ),
    path("crm/reports/", crm_views.CrmReportView.as_view(), name="crm_reports"),
    path("crm/reports/export.xlsx", crm_views.CrmReportExportView.as_view(), name="crm_reports_export"),
    path("work-orders/", WorkOrderListView.as_view(), name="work_orders"),
    path(
        "work-orders/<str:code>/sheet-template/",
        WorkOrderSheetTemplateView.as_view(),
        name="work_order_sheet_template",
    ),
    path(
        "work-orders/<str:code>/import/",
        WorkOrderImportView.as_view(),
        name="work_order_import",
    ),
    path("work-orders/<str:code>/", WorkOrderDetailView.as_view(), name="work_order_detail"),
    path("warehouse/", views.WarehouseListView.as_view(), name="warehouse"),
    path("procurement/", views.ProcurementListView.as_view(), name="procurement"),
    path("billing/", views.BillingListView.as_view(), name="billing"),
    path("accounting/", views.AccountingListView.as_view(), name="accounting"),
    path("documents/", views.DocumentsView.as_view(), name="documents"),
    path(
        "announcements/",
        announcement_views.AnnouncementListView.as_view(),
        name="announcements",
    ),
    path(
        "announcements/new/",
        announcement_views.AnnouncementCreateView.as_view(),
        name="announcement_create",
    ),
    path(
        "announcements/<int:pk>/edit/",
        announcement_views.AnnouncementUpdateView.as_view(),
        name="announcement_edit",
    ),
    path(
        "announcements/<int:pk>/delete/",
        announcement_views.AnnouncementDeleteView.as_view(),
        name="announcement_delete",
    ),
    path(
        "procedures/",
        building_procedure_views.BuildingProcedureListView.as_view(),
        name="building_procedures",
    ),
    path(
        "procedures/new/",
        building_procedure_views.BuildingProcedureCreateView.as_view(),
        name="building_procedure_create",
    ),
    path(
        "procedures/<int:pk>/edit/",
        building_procedure_views.BuildingProcedureUpdateView.as_view(),
        name="building_procedure_edit",
    ),
    path(
        "procedures/<int:pk>/delete/",
        building_procedure_views.BuildingProcedureDeleteView.as_view(),
        name="building_procedure_delete",
    ),
    path(
        "procedures/<int:pk>/download/",
        building_procedure_views.BuildingProcedureDownloadView.as_view(),
        name="building_procedure_download",
    ),
    path("reports/", views.ReportsView.as_view(), name="reports"),
    path("reports/sla/", views.SlaReportView.as_view(), name="sla_report"),
    path(
        "reports/sla/export.xlsx",
        views.SlaReportExportView.as_view(),
        name="sla_report_export",
    ),
    path("audit/", views.AuditLogView.as_view(), name="audit"),
]
