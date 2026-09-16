from django import forms
from django.utils.translation import gettext_lazy as _

from apps.property.models import Floor, Space
from apps.reception.models import VisitorType
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


class PortalGuestForm(forms.Form):
    first_name = forms.CharField(label=_("Ad"), max_length=80)
    last_name = forms.CharField(label=_("Soyad"), max_length=80)
    email = forms.EmailField(required=False, label=_("E-poçt"))
    phone = forms.CharField(required=False, label=_("Telefon"))
    host = forms.ModelChoiceField(queryset=ResidentEmployee.objects.none(), required=False, label=_("Host"))
    visit_type = forms.ModelChoiceField(
        queryset=VisitorType.objects.filter(is_active=True),
        required=False,
        label=_("Ziyarət tipi"),
    )
    space = forms.ModelChoiceField(queryset=Space.objects.none(), required=False, label=_("Sahə"))
    expected_arrival = forms.DateTimeField(
        required=False,
        label=_("Gözlənilən gəliş"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"],
    )
    location_note = forms.CharField(required=False, label=_("Qeyd"))

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields["host"].queryset = ResidentEmployee.objects.filter(company=company, is_active=True)
            self.fields["space"].queryset = Space.objects.filter(resident=company)
        for field in self.fields.values():
            field.widget.attrs["class"] = "cp-input"


class GuestVisitForm(forms.Form):
    fin_code = forms.CharField(label=_("FIN"), max_length=32)
    first_name = forms.CharField(label=_("Ad"), max_length=80)
    last_name = forms.CharField(label=_("Soyad"), max_length=80)
    phone = forms.CharField(required=False, label=_("Telefon"), max_length=64)
    company = forms.ModelChoiceField(queryset=ResidentCompany.objects.none(), label=_("Şirkət"))
    host = forms.ModelChoiceField(queryset=ResidentEmployee.objects.none(), required=False, label=_("Host"))
    id_document_held = forms.BooleanField(
        required=False,
        initial=False,
        label=_("Şəxsiyyət vəsiqəsi qəbul edildi"),
    )
    notes = forms.CharField(
        required=False,
        label=_("Qeyd"),
        widget=forms.TextInput(attrs={"placeholder": _("Qısa qeyd")}),
    )
    floor = forms.ModelChoiceField(queryset=Floor.objects.none(), required=False, label=_("Mərtəbə"))
    space = forms.ModelChoiceField(queryset=Space.objects.none(), required=False, label=_("Sahə"))

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = ResidentCompany.objects.filter(status="active")
        hosts = ResidentEmployee.objects.filter(is_active=True).select_related("company")
        if company:
            hosts = hosts.filter(company=company)
        self.fields["host"].queryset = hosts
        self.fields["floor"].queryset = Floor.objects.all()
        self.fields["space"].queryset = Space.objects.all()
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                continue
            field.widget.attrs["class"] = "cp-input"
        self.fields["fin_code"].widget.attrs["autocomplete"] = "off"
        self.fields["fin_code"].widget.attrs["id"] = "id_fin_code"
