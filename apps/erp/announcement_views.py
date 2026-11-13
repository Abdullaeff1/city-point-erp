"""ERP CRUD for portal announcements (A.8 Admin-first publish)."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from apps.accounts.mixins import StaffRequiredMixin
from apps.comms.announcements import can_publish_announcement
from apps.comms.models import Announcement, AnnouncementSource
from apps.erp.forms import AnnouncementForm


class AnnouncementPublishRequiredMixin(StaffRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_publish_announcement(request.user):
            raise PermissionDenied(
                _("Elan idarəetməsi yalnız Admin (və ya təyin olunmuş staff) üçündür.")
            )
        return super().dispatch(request, *args, **kwargs)


class AnnouncementListView(AnnouncementPublishRequiredMixin, ListView):
    template_name = "erp/announcements.html"
    context_object_name = "announcements"
    queryset = Announcement.objects.prefetch_related("companies").select_related("company")


class AnnouncementCreateView(AnnouncementPublishRequiredMixin, CreateView):
    template_name = "erp/announcement_form.html"
    form_class = AnnouncementForm
    model = Announcement
    success_url = reverse_lazy("erp:announcements")

    def get_initial(self):
        initial = super().get_initial()
        initial.setdefault("published_at", timezone.localdate())
        return initial

    def form_valid(self, form):
        form.instance.source = AnnouncementSource.MANUAL
        form.save()
        messages.success(self.request, _("Elan dərc olundu."))
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = _("Yeni elan")
        return ctx


class AnnouncementUpdateView(AnnouncementPublishRequiredMixin, UpdateView):
    template_name = "erp/announcement_form.html"
    form_class = AnnouncementForm
    model = Announcement
    success_url = reverse_lazy("erp:announcements")
    pk_url_kwarg = "pk"

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Elan yeniləndi."))
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = _("Elanı redaktə et")
        ctx["announcement"] = self.object
        return ctx


class AnnouncementDeleteView(AnnouncementPublishRequiredMixin, View):
    def post(self, request, pk):
        announcement = get_object_or_404(Announcement, pk=pk)
        title = announcement.title
        announcement.delete()
        messages.success(request, _("Elan silindi: %(title)s") % {"title": title})
        return redirect("erp:announcements")
