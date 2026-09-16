import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.integrations.adapters import MockWebsiteLeadAdapter
from apps.integrations.models import SyncLog, SyncStatus
from apps.property.models import CommercialStatus, Space


@require_GET
def public_spaces(request):
    """Public marketable spaces whitelist (Scope 4 stub)."""
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
            "description": s.public_description or "",
        }
        for s in qs
    ]
    return JsonResponse({"results": data, "count": len(data)})


@csrf_exempt
@require_POST
def public_leads(request):
    """Website → ERP lead ingest stub with duplicate-friendly external_id."""
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
    from apps.property.models import Space

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
