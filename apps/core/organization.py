"""Shared organization structure — used by tickets, FM, procurement, approvals.

TicketDepartment / TicketQueue remain the ticket-routing SoT for now; they may
link to OrgDepartment / OrgQueue via optional FK in a later migration.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Organization(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("Organization")
        verbose_name_plural = _("Organizations")

    def __str__(self):
        return self.name


class OrgDepartment(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="departments")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("organization", "code")
        ordering = ["name"]

    def __str__(self):
        return f"{self.organization.code}:{self.code}"


class OrgQueue(models.Model):
    department = models.ForeignKey(OrgDepartment, on_delete=models.CASCADE, related_name="queues")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("department", "code")
        ordering = ["name"]

    def __str__(self):
        return f"{self.department.code}:{self.code}"


class Team(models.Model):
    department = models.ForeignKey(OrgDepartment, on_delete=models.CASCADE, related_name="teams")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("department", "code")
        ordering = ["name"]

    def __str__(self):
        return f"{self.department.code}:{self.code}"
