from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AccountType(models.TextChoices):
    ASSET = "asset", _("Asset")
    LIABILITY = "liability", _("Liability")
    EQUITY = "equity", _("Equity")
    REVENUE = "revenue", _("Revenue")
    EXPENSE = "expense", _("Expense")


class Account(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=16, choices=AccountType.choices)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class JournalEntry(models.Model):
    code = models.CharField(max_length=32, unique=True)
    entry_date = models.DateField(default=timezone.localdate)
    memo = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=32, blank=True)
    posted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-entry_date", "-id"]
        verbose_name_plural = "journal entries"

    def __str__(self):
        return self.code


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    memo = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.entry_id}:{self.account_id}"
