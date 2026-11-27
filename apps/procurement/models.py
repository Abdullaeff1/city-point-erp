from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PRStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SUBMITTED = "submitted", _("Submitted")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    ORDERED = "ordered", _("Ordered")


class PRSource(models.TextChoices):
    MANUAL = "manual", _("Manual")
    LOW_STOCK = "low_stock", _("Low stock")
    WO = "wo", _("Work order")
    DEPARTMENT = "department", _("Department")


class POStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    PARTIAL = "partial", _("Partial")
    RECEIVED = "received", _("Received")
    CLOSED = "closed", _("Closed")
    CANCELLED = "cancelled", _("Cancelled")


class PurchaseRequest(models.Model):
    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=24, choices=PRStatus.choices, default=PRStatus.DRAFT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_requests",
    )
    source = models.CharField(max_length=24, choices=PRSource.choices, default=PRSource.MANUAL)
    notes = models.TextField(blank=True)
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_requests",
    )
    source_po = models.ForeignKey(
        "PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reorder_prs",
        help_text=_("Təkrar alışın mənbə satınalma sifarişi"),
    )
    reorder_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Təkrar alış forması: təchizatçı, sətir qiymətləri, valyuta"),
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code


class PRLine(models.Model):
    pr = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(
        "warehouse.SKU",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pr_lines",
    )
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=14, decimal_places=3, default=1)
    unit = models.CharField(max_length=16, default="pcs")

    def __str__(self):
        return f"{self.pr_id}:{self.description}"


class PurchaseOrder(models.Model):
    code = models.CharField(max_length=32, unique=True)
    supplier_party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
    )
    status = models.CharField(max_length=24, choices=POStatus.choices, default=POStatus.DRAFT)
    pr = models.ForeignKey(
        PurchaseRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
    )
    source_po = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reorders",
        help_text=_("Təkrar alışın mənbə sifarişi"),
    )
    ordered_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.code


class POLine(models.Model):
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=255)
    sku = models.ForeignKey(
        "warehouse.SKU",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="po_lines",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    received_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    pr_line = models.ForeignKey(
        "PRLine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="po_lines",
    )
    quote_line = models.ForeignKey(
        "RFQQuoteLine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="po_lines",
    )

    def __str__(self):
        return f"{self.po_id}:{self.description}"


class RFQ(models.Model):
    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=200, blank=True)
    pr = models.ForeignKey(
        PurchaseRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rfqs",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "RFQ"
        verbose_name_plural = "RFQs"

    def __str__(self):
        return self.code


class RFQDispatchChannel(models.TextChoices):
    DRAFT = "draft", _("Draft")
    MANUAL = "manual", _("Manual handoff")
    EMAIL = "email", _("Email")
    OUTBOX = "outbox", _("Outbox")


class QuoteLineResponseStatus(models.TextChoices):
    QUOTED = "quoted", _("Quoted")
    UNANSWERED = "unanswered", _("Unanswered")


class ComparisonCoverage(models.TextChoices):
    """Per PR-line × supplier coverage for comparison UI (not a DB field)."""

    NOT_INVITED = "NOT_INVITED", _("Not invited")
    INVITED_UNANSWERED = "INVITED_UNANSWERED", _("Invited unanswered")
    QUOTED = "QUOTED", _("Quoted")


class RFQInvitation(models.Model):
    """Supplier-specific invitation with persisted line scope."""

    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name="invitations")
    supplier_party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        related_name="rfq_invitations",
    )
    request_text = models.TextField(blank=True)
    dispatch_channel = models.CharField(
        max_length=16,
        choices=RFQDispatchChannel.choices,
        default=RFQDispatchChannel.DRAFT,
    )
    dispatch_ref = models.CharField(max_length=255, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="superseded_by",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rfq_invitations_created",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["rfq", "supplier_party"],
                condition=models.Q(is_active=True),
                name="uniq_active_rfq_invitation_supplier",
            )
        ]

    def __str__(self):
        return f"{self.rfq_id}:{self.supplier_party_id}"

    @property
    def is_dispatched(self) -> bool:
        return self.dispatched_at is not None


class RFQInvitationLine(models.Model):
    invitation = models.ForeignKey(
        RFQInvitation, on_delete=models.CASCADE, related_name="lines"
    )
    pr_line = models.ForeignKey(
        PRLine, on_delete=models.CASCADE, related_name="rfq_invitation_lines"
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3, default=1)

    class Meta:
        unique_together = [("invitation", "pr_line")]

    def __str__(self):
        return f"{self.invitation_id}:{self.pr_line_id}"


class RFQQuote(models.Model):
    """Supplier quote against an RFQ — header unit_price kept for legacy quotes."""

    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name="quotes")
    invitation = models.ForeignKey(
        RFQInvitation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quotes",
    )
    supplier_party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rfq_quotes",
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="AZN")
    lead_time_days = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    supplier_reference = models.CharField(max_length=120, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    is_selected = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["unit_price", "id"]

    def __str__(self):
        return f"{self.rfq_id}:{self.unit_price}"

    @property
    def has_line_pricing(self) -> bool:
        return self.lines.exists()


class RFQQuoteLine(models.Model):
    quote = models.ForeignKey(RFQQuote, on_delete=models.CASCADE, related_name="lines")
    pr_line = models.ForeignKey(
        PRLine, on_delete=models.CASCADE, related_name="rfq_quote_lines"
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3, default=1)
    unit = models.CharField(max_length=16, default="pcs")
    currency = models.CharField(max_length=8, default="AZN")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_rate = models.DecimalField(
        max_digits=6, decimal_places=4, null=True, blank=True
    )
    price_includes_vat = models.BooleanField(default=False)
    response_status = models.CharField(
        max_length=16,
        choices=QuoteLineResponseStatus.choices,
        default=QuoteLineResponseStatus.QUOTED,
    )

    class Meta:
        unique_together = [("quote", "pr_line")]

    def __str__(self):
        return f"{self.quote_id}:{self.pr_line_id}"


class PRLineAward(models.Model):
    """Portion of a PR line awarded to one supplier (may split across suppliers).

    Active + ``po_line`` null = reserved (unissued). Issuing a PO consumes the
    award atomically (sets ``po_line``). Deactivate to release unused allocation
    while preserving history.
    """

    pr = models.ForeignKey(
        PurchaseRequest, on_delete=models.CASCADE, related_name="line_awards"
    )
    pr_line = models.ForeignKey(
        PRLine, on_delete=models.CASCADE, related_name="awards"
    )
    quote_line = models.ForeignKey(
        RFQQuoteLine,
        on_delete=models.PROTECT,
        related_name="awards",
    )
    supplier_party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        related_name="pr_line_awards",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="AZN")
    vat_rate = models.DecimalField(
        max_digits=6, decimal_places=4, null=True, blank=True
    )
    price_includes_vat = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pr_line_awards",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    po_line = models.ForeignKey(
        "POLine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_awards",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # One active unissued award per (line, supplier); portions to
            # different suppliers are allowed. Issued awards keep history.
            models.UniqueConstraint(
                fields=["pr_line", "supplier_party"],
                condition=models.Q(is_active=True, po_line__isnull=True),
                name="uniq_active_unissued_pr_line_supplier_award",
            )
        ]

    def __str__(self):
        return f"{self.pr_line_id}->{self.supplier_party_id}:{self.qty}"


class PurchaseApprovalLimit(models.Model):
    """Monetary AZN ceiling a role may approve without Management escalation.

    Tax basis (net/gross/VAT) is not encoded here — Finance must confirm before
    local approval uses quoted totals as spending authority. PR lines currently
    carry no unit price; comparable money appears at RFQ quote / PO line stage.
    """

    role = models.CharField(max_length=32, unique=True)
    max_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text=_("Maksimum məbləğ (AZN). Miqdar deyil."),
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.role}:{self.max_amount} AZN"


class GoodsReceiptOperation(models.Model):
    """Durable idempotency record for a single goods-receipt submission."""

    MODE_FULL = "full"
    MODE_PARTIAL = "partial"
    MODE_CHOICES = (
        (MODE_FULL, _("Full")),
        (MODE_PARTIAL, _("Partial")),
    )

    operation_key = models.CharField(max_length=64, unique=True)
    po = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="receipt_operations",
    )
    warehouse = models.ForeignKey(
        "warehouse.Warehouse",
        on_delete=models.PROTECT,
        related_name="goods_receipt_operations",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="goods_receipt_operations",
    )
    mode = models.CharField(max_length=16, choices=MODE_CHOICES)
    payload_fingerprint = models.CharField(max_length=64)
    lines_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.operation_key
