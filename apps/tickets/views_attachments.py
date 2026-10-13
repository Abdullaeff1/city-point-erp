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
        TicketAttachment.objects.select_related("ticket"),
        pk=pk,
    )
    if not can_access_ticket_attachment(request.user, attachment.ticket):
        raise Http404()
    if not attachment.file:
        raise Http404()
    return FileResponse(
        attachment.file.open("rb"),
        as_attachment=True,
        filename=attachment.file.name.rsplit("/", 1)[-1],
    )
