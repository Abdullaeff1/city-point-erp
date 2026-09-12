from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class VisitStatus(models.TextChoices):
    WAITING = "waiting", _("Gözləyir")
    INSIDE = "inside", _("İçəridə")
    LEFT = "left", _("Çıxış")


class Guest(models.Model):
    full_name = models.CharField(max_length=160)

    def __str__(self):
        return self.full_name


class GuestVisit(models.Model):
    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="visits")
    company = models.ForeignKey(
        "residents.ResidentCompany", on_delete=models.CASCADE, related_name="guest_visits"
    )
    host = models.ForeignKey(
        "residents.ResidentEmployee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hosted_visits",
    )
    floor = models.ForeignKey("property.Floor", null=True, blank=True, on_delete=models.SET_NULL)
    space = models.ForeignKey("property.Space", null=True, blank=True, on_delete=models.SET_NULL)
    location_note = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=VisitStatus.choices, default=VisitStatus.WAITING)
    scheduled_for = models.DateField(default=timezone.localdate)
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.guest} / {self.company}"
