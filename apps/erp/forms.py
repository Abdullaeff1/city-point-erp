from django import forms
from django.utils.translation import gettext_lazy as _

from apps.property.models import Floor, Space
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.tickets.models import Ticket, TicketCategory, TicketPriority


class PortalTicketForm(forms.ModelForm):
    photo = forms.FileField(required=False, label=_("Foto / sənəd"))

    class Meta:
        model = Ticket
        fields = ("category", "space", "priority", "description")
        labels = {
            "category": _("Kateqoriya"),
            "space": _("Sahə"),
            "priority": _("Prioritet"),
            "description": _("Təsvir"),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": _("Problemi qısa təsvir edin...")}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = TicketCategory.objects.all()
        self.fields["priority"].initial = TicketPriority.NORMAL
        if company:
            self.fields["space"].queryset = Space.objects.filter(resident=company)
        for name, field in self.fields.items():
            if name != "photo":
                field.widget.attrs["class"] = "cp-input"


class GuestVisitForm(forms.Form):
    full_name = forms.CharField(label=_("Qonaq"))
    company = forms.ModelChoiceField(queryset=ResidentCompany.objects.none(), label=_("Rezident"))
    host = forms.ModelChoiceField(queryset=ResidentEmployee.objects.none(), required=False, label=_("Host"))
    floor = forms.ModelChoiceField(queryset=Floor.objects.none(), required=False, label=_("Mərtəbə"))
    space = forms.ModelChoiceField(queryset=Space.objects.none(), required=False, label=_("Sahə"))
    location_note = forms.CharField(required=False, label=_("Qeyd"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = ResidentCompany.objects.filter(status="active")
        self.fields["host"].queryset = ResidentEmployee.objects.filter(is_active=True)
        self.fields["floor"].queryset = Floor.objects.all()
        self.fields["space"].queryset = Space.objects.all()
        for field in self.fields.values():
            field.widget.attrs["class"] = "cp-input"
