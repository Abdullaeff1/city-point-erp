"""Protected ticket attachment download (staff dept + resident company)."""

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from apps.tickets.access import can_access_ticket_attachment
from apps.tickets.models import TicketAttachment


@login_required
@require_GET
def ticket_attachment_download(request, pk):
    attachment = get_object_or_404(
        TicketAttachment.objects.select_related("ticket", "document"),
        pk=pk,
    )
    scope_ids = getattr(request, "portal_company_ids", None)
    if not can_access_ticket_attachment(
        request.user,
        attachment.ticket,
        company_ids=scope_ids,
        attachment=attachment,
    ):
        raise Http404()
    # Prefer canonical archive file when linked.
    file_field = None
    if attachment.document_id and getattr(attachment.document, "file", None):
        file_field = attachment.document.file
    elif attachment.file:
        file_field = attachment.file
    if not file_field:
        raise Http404()
    return FileResponse(
        file_field.open("rb"),
        as_attachment=True,
        filename=file_field.name.rsplit("/", 1)[-1],
    )
