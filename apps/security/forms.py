"""Forms for security floor plans and devices."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.property.models import Floor
from apps.security.models import (
    DeviceType,
    PlanCategory,
    SecurityDevice,
    SecurityFloorPlan,
)


class PlanUploadForm(forms.Form):
    title = forms.CharField(max_length=200, label=_("Başlıq"))
    floor = forms.ModelChoiceField(queryset=Floor.objects.none(), label=_("Mərtəbə"))
    category = forms.ChoiceField(choices=PlanCategory.choices, label=_("Kateqoriya"))
    source_file = forms.FileField(label=_("DWG / DXF"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["floor"].queryset = Floor.objects.select_related("building").order_by(
            "building__name", "code"
        )
        for name, field in self.fields.items():
            if name != "source_file":
                field.widget.attrs.setdefault("class", "cp-input")


class RevisionUploadForm(forms.Form):
    source_file = forms.FileField(label=_("Yeni DWG / DXF"))


class DeviceForm(forms.ModelForm):
    class Meta:
        model = SecurityDevice
        fields = ("name", "device_type", "ip_address", "location_note", "is_active")
        labels = {
            "name": _("Ad"),
            "device_type": _("Tip"),
            "ip_address": _("IP"),
            "location_note": _("Qeyd"),
            "is_active": _("Aktiv"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "is_active":
                field.widget.attrs.setdefault("class", "cp-input")


class PinPlaceForm(forms.Form):
    device = forms.ModelChoiceField(queryset=SecurityDevice.objects.none())
    x_pct = forms.DecimalField(min_value=0, max_value=100, max_digits=6, decimal_places=2)
    y_pct = forms.DecimalField(min_value=0, max_value=100, max_digits=6, decimal_places=2)
    note = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, plan: SecurityFloorPlan | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = SecurityDevice.objects.filter(is_active=True)
        if plan is not None:
            from apps.security.models import DeviceType, PlanCategory

            if plan.category == PlanCategory.CAMERAS:
                qs = qs.filter(device_type=DeviceType.CAMERA)
            elif plan.category == PlanCategory.SIGNALING:
                qs = qs.filter(
                    device_type__in=[DeviceType.ALARM_PANEL, DeviceType.SENSOR]
                )
        self.fields["device"].queryset = qs.order_by("name")
