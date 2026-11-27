"""Where an in-app notification should open, for the portal the user is in."""

import re

from django.urls import reverse

from apps.comms.models import Notification
from apps.tickets.access import can_view_ticket
from apps.tickets.models import Ticket

TICKET_CODE_RE = re.compile(r"\bTK-\d+\b")


def user_notifications(user, *, namespace: str, limit: int | None = 100, company_ids=None, unread_only=False):
    queryset = Notification.objects.filter(user=user)
    if unread_only:
        queryset = queryset.filter(is_read=False)
    notes = list(
        queryset
        .select_related("ticket")
        .order_by("-created_at")[:limit]
    )
    visible_notes = []
    guest_prefix = "visitor.checked_in."
    overdue_prefix = "visitor.checkout_overdue."
    visible_guest_keys = set()
    visible_overdue_keys = set()
    if namespace == "portal" and company_ids is not None:
        from apps.reception.models import GuestVisit

        guest_ids = [n.event_key[len(guest_prefix):] for n in notes if n.event_key.startswith(guest_prefix)]
        visits = GuestVisit.objects.filter(company_id__in=company_ids, pk__in=[int(i) for i in guest_ids if i.isdecimal()])
        visible_guest_keys = {f"{guest_prefix}{pk}" for pk in visits.values_list("pk", flat=True)}
        overdue_visit_ids = []
        for n in notes:
            if not n.event_key.startswith(overdue_prefix):
                continue
            # visitor.checkout_overdue.{visit_id}.u.{user_id}
            parts = n.event_key[len(overdue_prefix) :].split(".")
            if parts and parts[0].isdecimal():
                overdue_visit_ids.append(int(parts[0]))
        overdue_ok = set(
            GuestVisit.objects.filter(
                company_id__in=company_ids, pk__in=overdue_visit_ids
            ).values_list("pk", flat=True)
        )
        for n in notes:
            if n.event_key.startswith(overdue_prefix):
                parts = n.event_key[len(overdue_prefix) :].split(".")
                if parts and parts[0].isdecimal() and int(parts[0]) in overdue_ok:
                    visible_overdue_keys.add(n.event_key)
    missing_codes = []
    for note in notes:
        if note.ticket_id:
            continue
        match = TICKET_CODE_RE.search(note.message or "")
        if match:
            missing_codes.append(match.group(0))
    by_code = {}
    if missing_codes:
        by_code = {
            ticket.code: ticket
            for ticket in Ticket.objects.filter(code__in=set(missing_codes))
        }
    drawing_prefix = "space_drawing_access_result:"
    visible_drawing_keys = set()
    if namespace == "portal" and company_ids is not None:
        from apps.property.models import SpaceDrawingAccessRequest

        drawing_ids = [
            n.event_key[len(drawing_prefix) :]
            for n in notes
            if n.event_key.startswith(drawing_prefix)
        ]
        req_pks = [int(i) for i in drawing_ids if i.isdecimal()]
        if req_pks:
            allowed = SpaceDrawingAccessRequest.objects.filter(
                pk__in=req_pks,
                drawing__space__resident_id__in=company_ids,
            ).values_list("pk", flat=True)
            visible_drawing_keys = {f"{drawing_prefix}{pk}" for pk in allowed}

    shared_prefix = "document.shared."
    visible_shared_keys = set()
    if namespace == "portal" and company_ids is not None:
        from apps.documents.models import Document

        shared_doc_ids = {}
        for n in notes:
            if n.event_key.startswith(shared_prefix):
                head = n.event_key[len(shared_prefix) :].split(".")[0]
                if head.isdecimal():
                    shared_doc_ids.setdefault(int(head), []).append(n.event_key)
        if shared_doc_ids:
            ok_ids = Document.objects.filter(
                pk__in=list(shared_doc_ids), company_id__in=company_ids
            ).values_list("pk", flat=True)
            for pk in ok_ids:
                visible_shared_keys.update(shared_doc_ids[pk])

    for note in notes:
        if (
            namespace == "portal"
            and company_ids is not None
            and note.event_key.startswith(shared_prefix)
            and note.event_key not in visible_shared_keys
        ):
            continue
        if namespace == "portal" and company_ids is not None and note.event_key.startswith(guest_prefix) and note.event_key not in visible_guest_keys:
            continue
        if (
            namespace == "portal"
            and company_ids is not None
            and note.event_key.startswith(overdue_prefix)
            and note.event_key not in visible_overdue_keys
        ):
            continue
        if (
            namespace == "portal"
            and company_ids is not None
            and note.event_key.startswith(drawing_prefix)
            and note.event_key not in visible_drawing_keys
        ):
            continue
        ticket = note.ticket if note.ticket_id else None
        if ticket is None:
            match = TICKET_CODE_RE.search(note.message or "")
            ticket = by_code.get(match.group(0)) if match else None
        if namespace == "portal" and company_ids is not None and ticket and ticket.company_id not in company_ids:
            continue
        note.target_url = notification_target_url(note, ticket, user, namespace, company_ids=company_ids)
        visible_notes.append(note)
    return visible_notes


def notification_target_url(note, ticket, user, namespace: str, *, company_ids=None) -> str:
    if ticket is not None:
        if namespace == "portal":
            company_id = getattr(user, "resident_company_id", None)
            if ticket.company_id in (company_ids if company_ids is not None else [company_id]):
                return reverse("portal:request_detail", kwargs={"code": ticket.code})
            return ""
        if namespace == "security":
            if can_view_ticket(user, ticket):
                return reverse("security:ticket_detail", kwargs={"code": ticket.code})
            return ""
        if can_view_ticket(user, ticket):
            return reverse("erp:ticket_detail", kwargs={"code": ticket.code})
        return ""

    key = (getattr(note, "event_key", None) or "").strip()
    if key.startswith("payment.evidence.") and namespace != "portal":
        from apps.accounts.models import Role

        if getattr(user, "role", None) == Role.ACCOUNTANT:
            return reverse("finance:payment_evidence")
        return ""
    if key.startswith("document.shared.") and namespace == "portal":
        head = key[len("document.shared.") :].split(".")[0]
        if head.isdecimal():
            from apps.documents.models import Document

            doc = (
                Document.objects.filter(pk=int(head))
                .select_related("invoice")
                .first()
            )
            if doc is not None and doc.invoice_id:
                return reverse("portal:invoice_detail", kwargs={"code": doc.invoice.code})
        return reverse("portal:documents")
    if key.startswith("space_drawing_access:") and namespace == "erp":
        return reverse("erp:drawing_access_queue")
    if key.startswith("space_drawing_access_result:") and namespace == "portal":
        # Resident opens own space list; detail link resolved after they pick space
        return reverse("portal:spaces")
    if key.startswith("approval.") and namespace == "erp":
        # Originators open their source record; Management hub stays for decidable roles.
        from apps.accounts.models import Role
        from apps.workflows.models import ApprovalRequest

        parts = key.split(".")
        approval_id = None
        if len(parts) >= 3 and parts[1] in {"decided", "requested"}:
            try:
                approval_id = int(parts[2])
            except (TypeError, ValueError):
                approval_id = None
        if approval_id:
            req = ApprovalRequest.objects.filter(pk=approval_id).first()
            if req is not None:
                code = req.workflow_code or ""
                payload = req.payload or {}
                if code == "document.approve":
                    from apps.documents.archive import can_browse_archive

                    # D08: the global archive is Management/Admin only — no dead link for departments.
                    return reverse("erp:documents") if can_browse_archive(user) else ""
                if code in {"procurement.pr", "procurement.commitment"}:
                    pr_code = payload.get("code")
                    if pr_code:
                        return reverse("erp:procurement_pr_detail", kwargs={"code": pr_code})
                    return reverse("erp:procurement")
                if code.startswith("crm.offer") or "offer" in code:
                    from apps.crm.access import can_view_crm

                    if not can_view_crm(user):
                        return ""
                    offer_id = payload.get("offer_id")
                    if offer_id:
                        return reverse("erp:crm_offer_detail", kwargs={"pk": offer_id})
                    return reverse("erp:crm_offers")
        if getattr(user, "role", None) in {Role.ADMIN, Role.MANAGEMENT}:
            return reverse("erp:approvals")
        return ""
    if key.startswith("crm.offer.rejected.") and namespace == "erp":
        from apps.crm.access import can_view_crm

        if not can_view_crm(user):
            return ""
        parts = key.split(".")
        try:
            offer_id = int(parts[3]) if len(parts) >= 4 else None
        except (TypeError, ValueError):
            offer_id = None
        if offer_id:
            return reverse("erp:crm_offer_detail", kwargs={"pk": offer_id})
        return reverse("erp:crm_offers")
    if key.startswith("crm.lease_app.submit.") and namespace == "erp":
        return reverse("erp:crm_lease_applications")
    if key.startswith("lease.activated.") and namespace == "erp":
        from apps.rbac.services import user_has_permission

        if not user_has_permission(user, "lease.view"):
            return ""
        parts = key.split(".")
        try:
            lease_id = int(parts[2]) if len(parts) >= 3 else None
        except (TypeError, ValueError):
            lease_id = None
        if lease_id:
            from apps.leases.models import Lease

            lease = Lease.objects.filter(pk=lease_id).only("code").first()
            if lease is not None:
                return reverse("erp:lease_detail", kwargs={"code": lease.code})
        return reverse("erp:dashboard")
    if key.startswith("procurement.po.") or key.startswith("po.received."):
        if namespace == "erp":
            return reverse("erp:procurement")
    if key.startswith("warehouse.issue.") and namespace == "erp":
        return reverse("erp:work_orders")
    if key.startswith("visitor.checked_in.") and namespace == "portal":
        return reverse("portal:guests")
    if key.startswith("visitor.checkout_overdue.") and namespace == "portal":
        parts = key[len("visitor.checkout_overdue.") :].split(".")
        visit_id = parts[0] if parts and parts[0].isdecimal() else ""
        if visit_id:
            return f"{reverse('portal:guests')}?overdue=1"
        return reverse("portal:guests")
    if key.startswith("visitor.id_held_overdue."):
        # Reception owns physical ID return; Security gets operational visibility.
        if namespace == "security":
            return f"{reverse('security:guests')}?status=inside_overdue"
        if namespace == "erp":
            return f"{reverse('erp:reception')}?status=inside_overdue"
    if key.startswith("visitor.return_pending.") or key.startswith("visitor.id_returned."):
        if namespace == "security":
            return f"{reverse('security:guests')}?status=id_pending"
        if namespace == "erp":
            return f"{reverse('erp:reception')}?status=id_pending"

    if namespace != "security":
        return ""
    message = note.message or ""
    if message.startswith("Kart çoxvurma"):
        return reverse("security:alerts_rapid")
    if message.startswith("Şaxta"):
        return reverse("security:alerts_shaft")
    if message.startswith("Qonaq çıxışı") or message.startswith("Vəsiqə"):
        return reverse("security:guests")
    return ""
