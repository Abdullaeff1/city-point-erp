from django.urls import path
from django.views.generic import RedirectView

from apps.erp import (
    announcement_views,
    building_procedure_views,
    crm_views,
    dashboard_views,
    drawing_views,
    it_views,
    management_views,
    resident_views,
    views,
)
from apps.erp.work_orders import (
    WorkOrderCreateView,
    WorkOrderDetailView,
    WorkOrderImportView,
    WorkOrderListView,
    WorkOrderSheetTemplateView,
)
from apps.erp.maintenance_views import (
    MaintenancePlanFormView,
    MaintenancePlanListView,
)
from apps.erp.warehouse_views import (
    WarehouseListView,
    WarehouseSkuCreateView,
    WarehouseSkuDetailView,
)
from apps.erp.stocktake_views import StocktakeDetailView, StocktakeListView
from apps.erp.correspondence_views import CorrespondenceDetailView, CorrespondenceListView
from apps.erp.procurement_views import (
    ProcurementListView,
    ProcurementPODetailView,
    ProcurementPRCreateView,
    ProcurementPRDetailView,
    ProcurementRFQDetailView,
    ProcurementSupplierDetailView,
    ProcurementSupplierFormView,
    ProcurementSupplierListView,
)

app_name = "erp"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path(
        "dashboards/supply/",
        dashboard_views.SupplyDashboardView.as_view(),
        name="supply_dashboard",
    ),
    path(
        "dashboards/facility/",
        dashboard_views.FacilityDashboardView.as_view(),
        name="facility_dashboard",
    ),
    path(
        "dashboards/helpdesk/",
        dashboard_views.HelpdeskDashboardView.as_view(),
        name="helpdesk_dashboard",
    ),
    path(
        "directory/residents/",
        resident_views.ResidentDirectoryListView.as_view(),
        name="resident_directory",
    ),
    path(
        "directory/residents/<slug:slug>/",
        resident_views.ResidentDirectoryDetailView.as_view(),
        name="resident_directory_detail",
    ),
    path(
        "dashboards/hr/",
        dashboard_views.HrDashboardView.as_view(),
        name="hr_dashboard",
    ),
    path(
        "dashboards/procurement/",
        dashboard_views.ProcurementDashboardView.as_view(),
        name="procurement_dashboard",
    ),
    path(
        "dashboards/it/",
        dashboard_views.ItDashboardView.as_view(),
        name="it_dashboard",
    ),
    path("staff-users/", it_views.StaffUserListView.as_view(), name="staff_users"),
    path(
        "staff-users/<int:pk>/",
        it_views.StaffUserDetailView.as_view(),
        name="staff_user_detail",
    ),
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
        "crm/offers/<int:pk>/versions/<int:version_id>/pdf/",
        crm_views.CrmOfferVersionPdfView.as_view(),
        name="crm_offer_version_pdf",
    ),
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
    path(
        "crm/spaces/",
        crm_views.CrmAvailableSpacesView.as_view(),
        name="crm_available_spaces",
    ),
    path(
        "crm/spaces/<str:code>/",
        crm_views.CrmSpaceDetailView.as_view(),
        name="crm_space_detail",
    ),
    path("work-orders/", WorkOrderListView.as_view(), name="work_orders"),
    path("work-orders/new/", WorkOrderCreateView.as_view(), name="work_order_create"),
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
    path("maintenance/plans/", MaintenancePlanListView.as_view(), name="maintenance_plans"),
    path(
        "maintenance/plans/new/",
        MaintenancePlanFormView.as_view(),
        name="maintenance_plan_create",
    ),
    path(
        "maintenance/plans/<int:pk>/",
        MaintenancePlanFormView.as_view(),
        name="maintenance_plan_edit",
    ),
    path("warehouse/", WarehouseListView.as_view(), name="warehouse"),
    path("warehouse/skus/new/", WarehouseSkuCreateView.as_view(), name="warehouse_sku_create"),
    path(
        "warehouse/skus/<str:code>/",
        WarehouseSkuDetailView.as_view(),
        name="warehouse_sku_detail",
    ),
    path("warehouse/stocktakes/", StocktakeListView.as_view(), name="stocktake_list"),
    path(
        "warehouse/stocktakes/<str:code>/",
        StocktakeDetailView.as_view(),
        name="stocktake_detail",
    ),
    path("procurement/", ProcurementListView.as_view(), name="procurement"),
    path("procurement/prs/new/", ProcurementPRCreateView.as_view(), name="procurement_pr_create"),
    path(
        "procurement/prs/<str:code>/",
        ProcurementPRDetailView.as_view(),
        name="procurement_pr_detail",
    ),
    path(
        "procurement/pos/<str:code>/",
        ProcurementPODetailView.as_view(),
        name="procurement_po_detail",
    ),
    path(
        "procurement/suppliers/",
        ProcurementSupplierListView.as_view(),
        name="procurement_suppliers",
    ),
    path(
        "procurement/suppliers/new/",
        ProcurementSupplierFormView.as_view(),
        name="procurement_supplier_create",
    ),
    path(
        "procurement/suppliers/<int:pk>/edit/",
        ProcurementSupplierFormView.as_view(),
        name="procurement_supplier_edit",
    ),
    path(
        "procurement/suppliers/<int:pk>/",
        ProcurementSupplierDetailView.as_view(),
        name="procurement_supplier_detail",
    ),
    path(
        "procurement/rfqs/<str:code>/",
        ProcurementRFQDetailView.as_view(),
        name="procurement_rfq_detail",
    ),
    path("billing/", views.BillingListView.as_view(), name="billing"),
    path("accounting/", views.AccountingListView.as_view(), name="accounting"),
    path("documents/", views.DocumentsView.as_view(), name="documents"),
    path(
        "documents/<int:pk>/download/",
        views.DocumentDownloadView.as_view(),
        name="document_download",
    ),
    path(
        "correspondence/",
        CorrespondenceListView.as_view(),
        name="correspondence_list",
    ),
    path(
        "correspondence/<int:pk>/",
        CorrespondenceDetailView.as_view(),
        name="correspondence_detail",
    ),
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
    path("reports/export.xlsx", views.ReportsExportView.as_view(), name="reports_export"),
    path(
        "reports/drill/<str:section>/",
        views.ReportsDrillView.as_view(),
        name="reports_drill",
    ),
    path("reports/sla/", views.SlaReportView.as_view(), name="sla_report"),
    path(
        "reports/sla/export.xlsx",
        views.SlaReportExportView.as_view(),
        name="sla_report_export",
    ),
    path("approvals/", management_views.ApprovalsView.as_view(), name="approvals"),
    path(
        "payment-approvals/",
        management_views.PaymentApprovalsView.as_view(),
        name="payment_approvals",
    ),
    path("ar-aging/", management_views.ArAgingView.as_view(), name="ar_aging"),
    path(
        "accounting-periods/",
        management_views.AccountingPeriodsView.as_view(),
        name="accounting_periods",
    ),
    path("audit/", views.AuditLogView.as_view(), name="audit"),
]
