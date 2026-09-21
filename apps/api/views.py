import json
import os

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.integrations.adapters import MockWebsiteLeadAdapter
from apps.integrations.models import SyncLog, SyncStatus
from apps.property.models import CommercialStatus, Space


def _public_api_authorized(request) -> bool:
    """Optional API key via PUBLIC_API_KEY env; if unset, allow (dev)."""
    expected = (os.environ.get("PUBLIC_API_KEY") or "").strip()
    if not expected:
        return True
    got = (request.headers.get("X-API-Key") or request.GET.get("api_key") or "").strip()
    return got == expected


@require_GET
def public_spaces(request):
    """Public marketable spaces whitelist."""
    if not _public_api_authorized(request):
        return JsonResponse({"error": {"code": "unauthorized", "message": "Invalid API key"}}, status=401)
    qs = (
        Space.objects.filter(is_public=True, commercial_status=CommercialStatus.VACANT)
        .select_related("floor", "floor__building")
        .order_by("code")
    )
    data = [
        {
            "code": s.code,
            "name": s.short_label,
            "floor": s.floor.code if s.floor_id else None,
            "building": s.floor.building.code if s.floor_id else None,
            "area_m2": float(s.rentable_area_m2 or s.area_m2 or 0),
            "base_rent_rate": float(s.base_rent_rate) if s.base_rent_rate is not None else None,
            "service_charge_rate": float(s.service_charge_rate) if s.service_charge_rate is not None else None,
            "availability_date": s.availability_date.isoformat() if s.availability_date else None,
            "description": s.public_description or "",
        }
        for s in qs
    ]
    return JsonResponse({"results": data, "count": len(data)})


@csrf_exempt
@require_POST
def public_leads(request):
    """Website → ERP lead ingest with optional API key + duplicate external_id."""
    if not _public_api_authorized(request):
        return JsonResponse({"error": {"code": "unauthorized", "message": "Invalid API key"}}, status=401)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"error": {"code": "invalid_json", "message": "Invalid JSON"}},
            status=400,
        )

    email = (payload.get("email") or "").strip()
    full_name = (payload.get("full_name") or "").strip()
    if not email or not full_name:
        return JsonResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "full_name and email are required",
                    "details": {},
                }
            },
            status=400,
        )

    from apps.crm.models import Lead, LeadSource, LeadStatus

    space = None
    space_code = payload.get("interested_space_code")
    if space_code:
        space = Space.objects.filter(code=space_code).first()

    adapter = MockWebsiteLeadAdapter()
    result = adapter.ingest_lead(payload)
    external_id = result.external_id

    lead, created = Lead.objects.get_or_create(
        external_id=external_id,
        defaults={
            "full_name": full_name,
            "email": email,
            "phone": (payload.get("phone") or "")[:64],
            "company_name": (payload.get("company_name") or "")[:200],
            "message": payload.get("message") or "",
            "source": LeadSource.WEBSITE,
            "status": LeadStatus.NEW,
            "interested_space": space,
        },
    )
    SyncLog.objects.create(
        system="website",
        operation="ingest_lead",
        status=SyncStatus.SUCCESS if result.ok else SyncStatus.ERROR,
        request_payload=payload,
        response_payload={"lead_id": lead.pk, "created": created},
        correlation_id=external_id,
    )
    return JsonResponse(
        {"id": lead.pk, "external_id": external_id, "created": created},
        status=201 if created else 200,
    )
