import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.services import DomainError
from apps.reception.models import GuestVisit, VisitStatus, mask_fin
from apps.reception.services import ReceptionService, filter_visits, today_visits_queryset
from apps.rbac.services import user_has_permission
from apps.residents.models import ResidentCompany, ResidentEmployee


def _deny(message="Forbidden", status=403):
    return JsonResponse({"error": {"code": "forbidden", "message": message}}, status=status)


def _require_perm(user, code):
    if not user_has_permission(user, code):
        return False
    return True


def _visit_payload(visit, *, can_sensitive=False):
    access = getattr(visit, "visitor_access", None)
    serial = visit.guest.fin_code if can_sensitive else mask_fin(visit.guest.fin_code)
    return {
        "id": visit.pk,
        "guest": visit.guest.display_name,
        "serial": serial,
        "fin": serial,  # legacy alias — value is ID series number
        "company": visit.company.name,
        "company_id": visit.company_id,
        "host": visit.host.full_name if visit.host_id else None,
        "visit_type": visit.visit_type.name if visit.visit_type_id else None,
        "status": visit.status,
        "check_in_at": visit.check_in_at.isoformat() if visit.check_in_at else None,
        "check_out_at": visit.check_out_at.isoformat() if visit.check_out_at else None,
        "id_document_held": visit.id_document_held,
        "invite_code": visit.invite_code,
        "access_status": access.status if access else None,
    }


@login_required
@require_http_methods(["GET", "POST"])
def reception_visits(request):
    if not _require_perm(request.user, "reception.view"):
        return _deny()
    can_sensitive = user_has_permission(request.user, "reception.view_sensitive_data")

    if request.method == "GET":
        qs = filter_visits(
            GuestVisit.objects.select_related(
                "guest", "company", "host", "visit_type", "visitor_access"
            ),
            q=request.GET.get("q", ""),
            status=request.GET.get("status", ""),
            company_id=request.GET.get("company") or None,
            id_not_returned=request.GET.get("id_not_returned") == "1",
        )[:100]
        return JsonResponse(
            {"results": [_visit_payload(v, can_sensitive=can_sensitive) for v in qs], "count": len(qs)}
        )

    if not _require_perm(request.user, "reception.create_visit"):
        return _deny("create_visit required")
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": {"code": "invalid_json", "message": "Invalid JSON"}}, status=400)

    company = ResidentCompany.objects.filter(pk=payload.get("company_id")).first()
    host = None
    if payload.get("host_id"):
        host = ResidentEmployee.objects.filter(pk=payload["host_id"]).first()
    visit_type = None
    if payload.get("visit_type_id"):
        from apps.reception.models import VisitorType

        visit_type = VisitorType.objects.filter(pk=payload["visit_type_id"]).first()
    try:
        visit = ReceptionService.register_walk_in(
            fin_code=payload.get("serial")
            or payload.get("serial_number")
            or payload.get("fin_code")
            or "",
            first_name=payload.get("first_name") or "",
            last_name=payload.get("last_name") or "",
            phone=payload.get("phone") or "",
            company=company,
            host=host,
            visit_type=visit_type,
            id_document_held=bool(payload.get("id_document_held")),
            id_override_reason=payload.get("id_override_reason") or "",
            notes=payload.get("notes") or "",
            actor=request.user,
            allow_id_override=user_has_permission(request.user, "reception.override_id"),
        )
    except DomainError as exc:
        return JsonResponse(
            {"error": {"code": "domain_error", "message": str(exc)}},
            status=400,
        )
    visit = GuestVisit.objects.select_related(
        "guest", "company", "host", "visit_type", "visitor_access"
    ).get(pk=visit.pk)
    return JsonResponse(_visit_payload(visit, can_sensitive=can_sensitive), status=201)


@login_required
@require_GET
def reception_visit_detail(request, pk):
    if not _require_perm(request.user, "reception.view"):
        return _deny()
    visit = get_object_or_404(
        GuestVisit.objects.select_related("guest", "company", "host", "visit_type", "visitor_access"),
        pk=pk,
    )
    return JsonResponse(
        _visit_payload(
            visit,
            can_sensitive=user_has_permission(request.user, "reception.view_sensitive_data"),
        )
    )


def _action_response(request, visit, action):
    allow_override = user_has_permission(request.user, "reception.override_id")
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {}
    try:
        if action == "check-in":
            if not _require_perm(request.user, "reception.check_in"):
                return _deny()
            visit = ReceptionService.check_in_visit(
                visit,
                actor=request.user,
                fin_code=payload.get("serial")
                or payload.get("serial_number")
                or payload.get("fin_code")
                or "",
                id_document_held=bool(payload.get("id_document_held")),
                id_override_reason=payload.get("id_override_reason") or "",
                allow_id_override=allow_override,
                first_name=payload.get("first_name") or "",
                last_name=payload.get("last_name") or "",
            )
        elif action == "check-out":
            if not _require_perm(request.user, "reception.check_out"):
                return _deny()
            visit = ReceptionService.check_out_visit(
                visit,
                actor=request.user,
                id_returned=payload.get("id_returned", True),
                allow_return_pending=allow_override and not payload.get("id_returned", True),
            )
        elif action == "cancel":
            if not _require_perm(request.user, "reception.cancel_visit"):
                return _deny()
            visit = ReceptionService.cancel_visit(visit, actor=request.user)
        else:
            return JsonResponse({"error": {"code": "unknown_action", "message": action}}, status=400)
    except DomainError as exc:
        return JsonResponse({"error": {"code": "domain_error", "message": str(exc)}}, status=400)
    visit.refresh_from_db()
    visit = GuestVisit.objects.select_related(
        "guest", "company", "host", "visit_type", "visitor_access"
    ).get(pk=visit.pk)
    return JsonResponse(
        _visit_payload(
            visit,
            can_sensitive=user_has_permission(request.user, "reception.view_sensitive_data"),
        )
    )


@login_required
@require_POST
def reception_visit_check_in(request, pk):
    visit = get_object_or_404(GuestVisit, pk=pk)
    return _action_response(request, visit, "check-in")


@login_required
@require_POST
def reception_visit_check_out(request, pk):
    visit = get_object_or_404(GuestVisit, pk=pk)
    return _action_response(request, visit, "check-out")


@login_required
@require_POST
def reception_visit_cancel(request, pk):
    visit = get_object_or_404(GuestVisit, pk=pk)
    return _action_response(request, visit, "cancel")


@login_required
@require_GET
def reception_guest_search(request):
    if not _require_perm(request.user, "reception.search"):
        return _deny()
    fin = (
        request.GET.get("serial")
        or request.GET.get("serial_number")
        or request.GET.get("fin")
        or request.GET.get("q")
        or ""
    )
    guest = ReceptionService.find_guest_by_fin(fin)
    if not guest and fin:
        from apps.reception.models import Guest
        from django.db.models import Q

        q = fin.strip()
        guest = Guest.objects.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(full_name__icontains=q)
        ).first()
    if not guest:
        return JsonResponse({"results": [], "count": 0})
    can_sensitive = user_has_permission(request.user, "reception.view_sensitive_data")
    serial = guest.fin_code if can_sensitive else mask_fin(guest.fin_code)
    return JsonResponse(
        {
            "results": [
                {
                    "id": guest.pk,
                    "first_name": guest.first_name,
                    "last_name": guest.last_name,
                    "display_name": guest.display_name,
                    "serial": serial,
                    "fin": serial,  # legacy alias
                    "phone": guest.phone,
                }
            ],
            "count": 1,
        }
    )


@login_required
@require_GET
def reception_today(request):
    if not _require_perm(request.user, "reception.view"):
        return _deny()
    can_sensitive = user_has_permission(request.user, "reception.view_sensitive_data")
    qs = today_visits_queryset()
    return JsonResponse(
        {
            "date": timezone.localdate().isoformat(),
            "stats": {
                "today": qs.count(),
                "inside": GuestVisit.objects.filter(status=VisitStatus.INSIDE).count(),
                "checked_out": qs.filter(status=VisitStatus.LEFT).count(),
                "pre_registered": qs.filter(status=VisitStatus.PRE_REGISTERED).count(),
                "no_show": qs.filter(status=VisitStatus.NO_SHOW).count(),
                "id_pending": GuestVisit.objects.filter(status=VisitStatus.RETURN_PENDING).count(),
            },
            "results": [
                _visit_payload(v, can_sensitive=can_sensitive)
                for v in qs.select_related("guest", "company", "host", "visit_type", "visitor_access")
            ],
        }
    )
