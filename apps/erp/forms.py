from datetime import datetime, time, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from apps.property.models import Floor, Space
from apps.reception.models import VisitorType
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.tickets.models import Ticket, TicketCategory, TicketPriority, TicketSubcategory, TicketType
from apps.tickets.services import allowed_resident_priorities

# Portal guest arrival: 24h clock, no AM/PM; earliest hour 09:00.
ARRIVAL_HOUR_CHOICES = [(f"{h:02d}", f"{h:02d}") for h in range(9, 24)]
ARRIVAL_MINUTE_CHOICES = [(f"{m:02d}", f"{m:02d}") for m in range(0, 60, 5)]


class ExpectedArrival24hWidget(forms.MultiWidget):
    """Date + hour + minute selects (24-hour labels, no AM/PM)."""

    def __init__(self, attrs=None):
        widgets = [
            forms.DateInput(attrs={"type": "date", "class": "cp-input"}),
            forms.Select(attrs={"class": "cp-input", "aria-label": str(_("Saat"))}, choices=ARRIVAL_HOUR_CHOICES),
            forms.Select(
                attrs={"class": "cp-input", "aria-label": str(_("Dəqiqə"))},
                choices=ARRIVAL_MINUTE_CHOICES,
            ),
        ]
        super().__init__(widgets, attrs)

    def decompress(self, value):
        if not value:
            return [None, "", ""]
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        minute = (local.minute // 5) * 5
        return [local.date(), f"{local.hour:02d}", f"{minute:02d}"]

    def render(self, name, value, attrs=None, renderer=None):
        # Avoid custom form-widget templates (form renderer may miss project/app dirs).
        if self.is_localized:
            for widget in self.widgets:
                widget.is_localized = self.is_localized
        if not isinstance(value, list):
            value = self.decompress(value)
        final_attrs = self.build_attrs(attrs or {})
        id_ = final_attrs.get("id")
        parts = []
        for i, widget in enumerate(self.widgets):
            try:
                widget_value = value[i]
            except IndexError:
                widget_value = None
            widget_attrs = final_attrs.copy()
            if id_:
                widget_attrs["id"] = f"{id_}_{i}"
            parts.append(widget.render(f"{name}_{i}", widget_value, widget_attrs, renderer))
        return format_html(
            '<div class="cp-arrival-24h">{}{}<span class="cp-arrival-24h__sep" aria-hidden="true">:</span>{}</div>',
            mark_safe(parts[0]),
            mark_safe(parts[1]),
            mark_safe(parts[2]),
        )

class ExpectedArrival24hField(forms.MultiValueField):
    widget = ExpectedArrival24hWidget

    def __init__(self, **kwargs):
        fields = (
            forms.DateField(),
            forms.ChoiceField(choices=ARRIVAL_HOUR_CHOICES),
            forms.ChoiceField(choices=ARRIVAL_MINUTE_CHOICES),
        )
        kwargs.setdefault("require_all_fields", False)
        super().__init__(fields=fields, **kwargs)

    def compress(self, data_list):
        if not data_list:
            return None
        date_value, hour, minute = (list(data_list) + [None, None, None])[:3]
        # Optional field: no date means no expected arrival (hour/minute selects always post).
        if not date_value:
            return None
        if hour in (None, "") or minute in (None, ""):
            raise ValidationError(_("Saat və dəqiqəni seçin."), code="incomplete")
        hour_i = int(hour)
        minute_i = int(minute)
        if hour_i < 9:
            raise ValidationError(_("Gözlənilən gəliş ən tez 09:00 ola bilər."), code="before_nine")
        naive = datetime.combine(date_value, time(hour_i, minute_i))
        return timezone.make_aware(naive, timezone.get_current_timezone())

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
    email = forms.EmailField(
        required=False,
        label=_("E-poçt (istəyə bağlı)"),
    )
    phone = forms.CharField(
        required=False,
        label=_("Telefon (istəyə bağlı)"),
        max_length=64,
    )
    host = forms.ModelChoiceField(queryset=ResidentEmployee.objects.none(), required=False, label=_("Host"))
    visit_type = forms.ModelChoiceField(
        queryset=VisitorType.objects.filter(is_active=True),
        required=False,
        label=_("Ziyarət tipi"),
    )
    space = forms.ModelChoiceField(queryset=Space.objects.none(), required=False, label=_("Sahə"))
    expected_arrival = ExpectedArrival24hField(
        required=False,
        label=_("Gözlənilən gəliş"),
        help_text=_("24 saat formatı · ən tez 09:00 · növbəti 24 saat ərzində."),
    )
    location_note = forms.CharField(required=False, label=_("Qeyd"))

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields["host"].queryset = ResidentEmployee.objects.filter(company=company, is_active=True)
            self.fields["space"].queryset = Space.objects.filter(resident=company)
        now = timezone.localtime()
        date_widget = self.fields["expected_arrival"].widget.widgets[0]
        date_widget.attrs["min"] = now.date().isoformat()
        date_widget.attrs["max"] = (now + timedelta(hours=24)).date().isoformat()
        for name, field in self.fields.items():
            if name == "expected_arrival":
                continue
            field.widget.attrs["class"] = "cp-input"
            field.widget.attrs.pop("required", None)
            if name in ("email", "phone"):
                field.required = False

    def clean_expected_arrival(self):
        value = self.cleaned_data.get("expected_arrival")
        if value is None:
            return value
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        local = timezone.localtime(value)
        if local.hour < 9:
            raise ValidationError(_("Gözlənilən gəliş ən tez 09:00 ola bilər."))
        now = timezone.now()
        earliest = now - timedelta(minutes=5)
        latest = now + timedelta(hours=24)
        if value < earliest or value > latest:
            raise ValidationError(_("Gözlənilən gəliş növbəti 24 saat ərzində olmalıdır."))
        return value


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
        label=_("Şəxsiyyət vəsiqəsi saxlanıldı (qonaq kartı verildi)"),
    )
    guest_card_number = forms.CharField(
        required=False,
        label=_("Qonaq kartı №"),
        max_length=64,
        widget=forms.TextInput(attrs={"placeholder": _("Kart nömrəsi"), "autocomplete": "off"}),
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
        self.fields["guest_card_number"].widget.attrs["id"] = "id_guest_card_number"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("id_document_held") and not (cleaned.get("guest_card_number") or "").strip():
            self.add_error("guest_card_number", _("Qonaq kartı nömrəsi tələb olunur."))
        return cleaned
