from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.property.models import Floor, Space
from apps.reception.models import VisitorType
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.tickets.models import Ticket, TicketCategory, TicketPriority, TicketSubcategory, TicketType
from apps.tickets.services import allowed_resident_priorities


class PortalEmployeeCreateForm(forms.Form):
    full_name = forms.CharField(
        max_length=160,
        label=_("Əməkdaşın adı"),
        widget=forms.TextInput(attrs={"class": "cp-input", "placeholder": _("Ad Soyad")}),
    )
    access_level = forms.ChoiceField(
        label=_("İstənilən kart səviyyəsi"),
        choices=[
            ("1", _("Səviyyə 1 — arxa turniket (turn_back) yox")),
            ("2", _("Səviyyə 2 — arxa turniket (turn_back) icazəli")),
        ],
        initial="1",
        widget=forms.RadioSelect,
        help_text=_("Kart sifarişi üçün. Faktiki səviyyə AxTraxNG-də təyin olunandan sonra sync ilə gəlir."),
    )
    id_document = forms.FileField(
        label=_("Şəxsiyyət vəsiqəsi"),
        help_text=_("PDF, JPG və ya PNG (maks. 10 MB)."),
        widget=forms.ClearableFileInput(attrs={"class": "cp-input", "accept": ".pdf,.jpg,.jpeg,.png"}),
    )

    def clean_full_name(self):
        value = (self.cleaned_data.get("full_name") or "").strip()
        if not value:
            raise forms.ValidationError(_("Əməkdaşın adı mütləqdir."))
        return value

    def clean_id_document(self):
        from apps.residents.services import validate_id_document

        uploaded = self.cleaned_data.get("id_document")
        try:
            validate_id_document(uploaded)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return uploaded


class PortalTicketForm(forms.ModelForm):
    photo = forms.FileField(required=False, label=_("Foto / sənəd"))
    ticket_type = forms.ChoiceField(choices=TicketType.choices, label=_("Müraciət tipi"))
    subcategory = forms.ModelChoiceField(
        queryset=TicketSubcategory.objects.none(),
        label=_("Alt kateqoriya"),
    )
    resident_priority_suggestion = forms.ChoiceField(
        choices=allowed_resident_priorities(),
        required=False,
        initial=TicketPriority.NORMAL,
        label=_("Təxmini prioritet"),
    )

    class Meta:
        model = Ticket
        fields = ("ticket_type", "category", "subcategory", "space", "description")
        labels = {
            "category": _("Kateqoriya"),
            "space": _("Sahə"),
            "description": _("Təsvir"),
        }
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 4, "placeholder": _("Problemi qısa təsvir edin...")}
            ),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = TicketCategory.objects.filter(is_active=True)
        self.fields["space"].required = False
        self.fields["ticket_type"].initial = TicketType.INCIDENT

        category_id = None
        if self.data.get("category"):
            category_id = self.data.get("category")
        elif self.initial.get("category"):
            category_id = getattr(self.initial["category"], "pk", self.initial["category"])

        if category_id:
            self.fields["subcategory"].queryset = TicketSubcategory.objects.filter(
                is_active=True, category_id=category_id
            )
        else:
            self.fields["subcategory"].queryset = TicketSubcategory.objects.none()

        if company:
            self.fields["space"].queryset = Space.objects.filter(resident=company)
        for name, field in self.fields.items():
            if name != "photo":
                field.widget.attrs["class"] = "cp-input"

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category")
        subcategory = cleaned.get("subcategory")
        description = (cleaned.get("description") or "").strip()
        if subcategory and category and subcategory.category_id != category.id:
            self.add_error("subcategory", _("Alt kateqoriya seçilmiş kateqoriyaya aid deyil."))
        if subcategory and subcategory.requires_description_min:
            if len(description) < subcategory.requires_description_min:
                self.add_error(
                    "description",
                    _("Digər seçimində ən az %(n)s simvol yazın.")
                    % {"n": subcategory.requires_description_min},
                )
        return cleaned


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
    fin_code = forms.CharField(
        label=_("Seriya nömrəsi"),
        max_length=32,
        help_text=_("Şəxsiyyət vəsiqəsindəki seriya nömrəsi"),
    )
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
        self.fields["company"].queryset = ResidentCompany.objects.filter(status="active", is_internal=False)
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
        self.fields["fin_code"].widget.attrs["placeholder"] = _("Seriya №")
