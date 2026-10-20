from datetime import datetime, time, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from apps.core.search import fold_search
from apps.property.models import Floor, Space
from apps.reception.models import VisitorType
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.tickets.models import Ticket, TicketCategory, TicketPriority, TicketSubcategory, TicketType
from apps.tickets.services import allowed_resident_priorities, allowed_staff_priorities, citypoint_ticket_assignees

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


class StaffTicketForm(forms.Form):
    company = forms.ModelChoiceField(
        queryset=ResidentCompany.objects.none(),
        label=_("Şirkət"),
    )
    space = forms.ModelChoiceField(
        queryset=Space.objects.none(),
        required=False,
        label=_("Sahə"),
    )
    ticket_type = forms.ChoiceField(choices=TicketType.choices, label=_("Müraciət tipi"))
    category = forms.ModelChoiceField(
        queryset=TicketCategory.objects.none(),
        label=_("Problem"),
    )
    subcategory = forms.ModelChoiceField(
        queryset=TicketSubcategory.objects.none(),
        label=_("Alt problem"),
    )
    priority = forms.ChoiceField(
        choices=[("", _("Avtomatik"))] + list(allowed_staff_priorities()),
        required=False,
        label=_("Prioritet"),
    )
    assigned_employee = forms.ModelChoiceField(
        queryset=ResidentEmployee.objects.none(),
        required=False,
        label=_("Cavabdeh"),
    )
    description = forms.CharField(
        label=_("Təsvir"),
        widget=forms.Textarea(
            attrs={"rows": 5, "placeholder": _("Problemi ətraflı yazın...")}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = ResidentCompany.objects.filter(status="active").order_by("name")
        self.fields["space"].queryset = Space.objects.filter(resident__status="active").order_by("code")
        self.fields["category"].queryset = TicketCategory.objects.filter(is_active=True).order_by(
            "sort_order", "name"
        )
        self.fields["assigned_employee"].queryset = citypoint_ticket_assignees()
        self.fields["ticket_type"].initial = TicketType.INCIDENT
        category_id = self.data.get("category") if self.data else None
        if category_id:
            self.fields["subcategory"].queryset = TicketSubcategory.objects.filter(
                is_active=True, category_id=category_id
            )
        else:
            self.fields["subcategory"].queryset = TicketSubcategory.objects.filter(is_active=True)
        for field in self.fields.values():
            field.widget.attrs["class"] = "cp-input"
        self.fields["company"].widget.attrs["hidden"] = True
        self.fields["assigned_employee"].widget.attrs["hidden"] = True

    def clean(self):
        cleaned = super().clean()
        company = cleaned.get("company")
        space = cleaned.get("space")
        category = cleaned.get("category")
        subcategory = cleaned.get("subcategory")
        description = (cleaned.get("description") or "").strip()
        if space and company and space.resident_id != company.id:
            self.add_error("space", _("Sahə seçilmiş şirkətə aid deyil."))
        if subcategory and category and subcategory.category_id != category.id:
            self.add_error("subcategory", _("Alt problem seçilmiş problemə aid deyil."))
        if subcategory and subcategory.requires_description_min:
            if len(description) < subcategory.requires_description_min:
                self.add_error(
                    "description",
                    _("Bu problem üçün ən az %(n)s simvol yazın.")
                    % {"n": subcategory.requires_description_min},
                )
        cleaned["description"] = description
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


FORGOTTEN_CARD_CODE = "forgotten-card"
LEASE_AREA_CODE = "lease-area"
MEETING_CODE = "meeting"
TECHNICIAN_CODE = "technician"
PATIENT_CODE = "patient"
CITY_POINT_SLUG = "city-point"
PSYCHOLOGIST_SLUG_PREFIX = "psixoloq"
PSYCHOLOGIST_HOST_NAME = "LEYLA TƏBRİZ ŞAMİLOVA"
NO_HOST_VISIT_CODES = {FORGOTTEN_CARD_CODE, LEASE_AREA_CODE, MEETING_CODE, TECHNICIAN_CODE}


def psychologist_host(company):
    target = fold_search(PSYCHOLOGIST_HOST_NAME)
    for employee in ResidentEmployee.objects.filter(company=company, is_active=True):
        if fold_search(employee.full_name) == target:
            return employee
    return None


class VisitTypeSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-code"] = instance.code
        if instance is not None and instance.code in NO_HOST_VISIT_CODES:
            option["attrs"]["data-no-host"] = "1"
        if instance is not None and instance.code == LEASE_AREA_CODE:
            option["attrs"]["data-lock-company"] = CITY_POINT_SLUG
        return option


class GuestVisitForm(forms.Form):
    fin_code = forms.CharField(
        label=_("Seriya nömrəsi"),
        max_length=32,
        required=False,
        help_text=_("İstəyə bağlı — vəsiqə saxlanılanda tələb olunur (kuryer üçün boş buraxıla bilər)"),
    )
    first_name = forms.CharField(label=_("Ad"), max_length=80)
    last_name = forms.CharField(label=_("Soyad"), max_length=80)
    phone = forms.CharField(required=False, label=_("Telefon"), max_length=64)
    company = forms.ModelChoiceField(queryset=ResidentCompany.objects.none(), label=_("Şirkət"))
    host = forms.ModelChoiceField(queryset=ResidentEmployee.objects.none(), required=False, label=_("Host"))
    visit_type = forms.ModelChoiceField(
        queryset=VisitorType.objects.filter(is_active=True),
        label=_("Gəliş səbəbi"),
        empty_label=_("Seçin…"),
        widget=VisitTypeSelect,
    )
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
        max_length=500,
        widget=forms.TextInput(
            attrs={"placeholder": _("Qısa qeyd"), "maxlength": "500"}
        ),
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
        held = cleaned.get("id_document_held")
        if held and not (cleaned.get("guest_card_number") or "").strip():
            self.add_error("guest_card_number", _("Qonaq kartı nömrəsi tələb olunur."))
        if held and not (cleaned.get("fin_code") or "").strip():
            self.add_error("fin_code", _("Vəsiqə saxlanılanda seriya nömrəsi tələb olunur."))
        visit_type = cleaned.get("visit_type")
        if visit_type is not None and visit_type.code == LEASE_AREA_CODE:
            company = ResidentCompany.objects.filter(slug=CITY_POINT_SLUG, status="active").first()
            if company is None:
                self.add_error("company", _("City Point şirkəti tapılmadı."))
            else:
                cleaned["company"] = company
        company = cleaned.get("company")
        if company is not None and (company.slug or "").startswith(PSYCHOLOGIST_SLUG_PREFIX):
            patient = VisitorType.objects.filter(code=PATIENT_CODE, is_active=True).first()
            if patient is None:
                self.add_error("visit_type", _("Pasiyent gəliş səbəbi tapılmadı."))
            else:
                cleaned["visit_type"] = patient
                visit_type = patient
            host = psychologist_host(company)
            if host is None:
                self.add_error("host", _("Leyla Təbriz Şamilova tapılmadı."))
            else:
                cleaned["host"] = host
        if visit_type is not None and visit_type.code in NO_HOST_VISIT_CODES:
            cleaned["host"] = None
        return cleaned
