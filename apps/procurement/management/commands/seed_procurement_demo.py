"""Demo satınalma simulyasiyası: podratçılar → PR → RFQ → PO → qəbul → anbar."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType
from apps.procurement.models import PurchaseApprovalLimit, PurchaseRequest
from apps.procurement.services import ProcurementService
from apps.rbac.services import seed_rbac_catalog
from apps.warehouse.models import SKU, Stock, Warehouse

User = get_user_model()

DEMO_TAG = "DEMO-PROC-2026"
SUPPLIERS = [
    ("DEMO-SUP-ALPHA", "Alpha Texnika MMC", "Alpha Supply", "alpha@demo-supply.az", "+994501110001"),
    ("DEMO-SUP-BETA", "Beta Material MMC", "Beta Materials", "beta@demo-supply.az", "+994501110002"),
    ("DEMO-SUP-GAMMA", "Gamma Elektrik MMC", "Gamma Electric", "gamma@demo-supply.az", "+994501110003"),
    ("DEMO-SUP-DELTA", "Delta HVAC Servis", "Delta HVAC", "delta@demo-supply.az", "+994501110004"),
    ("DEMO-SUP-EPS", "Epsilon Təchizat ASC", "Epsilon Trade", "epsilon@demo-supply.az", "+994501110005"),
]
SKUS = [
    ("DEMO-FLT", "HVAC Filter G4", "pcs", "8", "12"),
    ("DEMO-OIL", "Kompressor yağı", "L", "5", "20"),
    ("DEMO-CBL", "İdarə kabeli 3x1.5", "m", "50", "100"),
    ("DEMO-LED", "LED panel 40W", "pcs", "10", "15"),
]


class Command(BaseCommand):
    help = (
        "Demo satınalma: 5 podratçı, PR→təsdiq→RFQ müqayisə→PO→qəbul; "
        "nəticə anbarda görünür. Təkrar işlətmək təhlükəsizdir."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Mövcud DEMO-PROC PR olsa belə yeni simulyasiya yarat.",
        )

    def handle(self, *args, **options):
        from django.conf import settings
        import os

        cp_env = getattr(settings, "CP_ENV", "development")
        if cp_env == "production":
            raise CommandError("seed_procurement_demo production-da qadağandır.")
        if cp_env != "development" and os.environ.get("SEED_DEMO", "0") != "1":
            raise CommandError(f"CP_ENV={cp_env}: yalnız SEED_DEMO=1 ilə.")

        seed_rbac_catalog()
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("10000.00"), "is_active": True},
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.ADMIN,
            defaults={"max_amount": Decimal("50000.00"), "is_active": True},
        )

        actor = (
            User.objects.filter(role=Role.SERVICE_DESK, is_active=True).order_by("id").first()
            or User.objects.filter(role=Role.ADMIN, is_active=True).order_by("id").first()
        )
        if actor is None:
            raise CommandError("FM və ya Admin istifadəçi tapılmadı — əvvəl seed_demo işlədin.")

        admin = (
            User.objects.filter(role=Role.ADMIN, is_active=True).order_by("id").first() or actor
        )

        if not options["force"] and PurchaseRequest.objects.filter(notes__contains=DEMO_TAG).exists():
            pr = PurchaseRequest.objects.filter(notes__contains=DEMO_TAG).order_by("-id").first()
            self.stdout.write(
                self.style.WARNING(
                    f"Demo artıq var: {pr.code}. Yenidən yaratmaq üçün --force."
                )
            )
            self._print_summary(pr)
            return

        with transaction.atomic():
            suppliers = self._ensure_suppliers()
            wh, sku_rows = self._ensure_warehouse_skus()
            before = {
                code: Stock.objects.filter(sku=sku, warehouse=wh).first()
                for code, sku, _qty in sku_rows
            }
            before_qty = {
                code: (s.quantity if s else Decimal("0")) for code, s in before.items()
            }

            pr = ProcurementService.create_manual_pr(
                actor=actor,
                title="Demo: FM ehtiyat materialları (filter, yağ, kabel, LED)",
                notes=(
                    f"{DEMO_TAG} Tam satınalma simulyasiyası — "
                    "RFQ müqayisə, PO, iki mərhələli qəbul, anbar artımı."
                ),
                lines=[
                    {
                        "sku_id": sku.pk,
                        "description": sku.name,
                        "qty": qty,
                        "unit": sku.unit,
                    }
                    for _code, sku, qty in sku_rows
                ],
            )
            ProcurementService.approve_pr(pr, actor=admin)

            rfq = ProcurementService.create_rfq_from_pr(pr, actor=actor)
            # Unit prices for single-price RFQ model (applied to all remaining qty).
            quotes = [
                ProcurementService.add_rfq_quote(
                    rfq,
                    supplier_party=suppliers[0],
                    unit_price="18.50",
                    lead_time_days=7,
                    notes="Alpha — tam paket",
                    actor=actor,
                ),
                ProcurementService.add_rfq_quote(
                    rfq,
                    supplier_party=suppliers[1],
                    unit_price="16.00",
                    lead_time_days=5,
                    notes="Beta — ən ucuz müqayisəolunan",
                    actor=actor,
                ),
                ProcurementService.add_rfq_quote(
                    rfq,
                    supplier_party=suppliers[2],
                    unit_price="17.25",
                    lead_time_days=4,
                    notes="Gamma",
                    actor=actor,
                ),
                ProcurementService.add_rfq_quote(
                    rfq,
                    supplier_party=suppliers[3],
                    unit_price="19.00",
                    lead_time_days=3,
                    notes="Delta — sürətli çatdırılma",
                    actor=actor,
                ),
            ]
            # Epsilon listed as supplier but not quoting this RFQ (catalog only).
            _ = suppliers[4]

            winner = min(quotes, key=lambda q: (q.unit_price, q.pk))
            assessed = ProcurementService.assess_quote_amount(winner, pr)
            po = ProcurementService.select_rfq_quote_and_create_po(winner, actor=actor)

            lines = list(po.lines.select_related("sku").order_by("pk"))
            # Two deliveries so operator sees partial → received.
            first = {ln.pk: str((ln.qty / 2).quantize(Decimal("0.001"))) for ln in lines}
            second = {
                ln.pk: str(ln.qty - Decimal(first[ln.pk])) for ln in lines
            }
            ProcurementService.receive_po(
                po,
                warehouse=wh,
                actor=actor,
                receive_mode="partial",
                line_qtys=first,
                operation_key=f"{DEMO_TAG}-R1",
            )
            ProcurementService.receive_po(
                po,
                warehouse=wh,
                actor=actor,
                receive_mode="partial",
                line_qtys=second,
                operation_key=f"{DEMO_TAG}-R2",
            )

        pr.refresh_from_db()
        po.refresh_from_db()
        self.stdout.write(self.style.SUCCESS("Demo satınalma tamamlandı."))
        self.stdout.write(f"  Actor: {actor.username} / approve: {admin.username}")
        self.stdout.write(f"  Podratçılar: {', '.join(s.display_name for s in suppliers)}")
        self.stdout.write(f"  PR: {pr.code} → {pr.get_status_display()}")
        self.stdout.write(f"  RFQ: {rfq.code} · seçilmiş: {winner.supplier_party.display_name} @ {winner.unit_price} AZN")
        self.stdout.write(
            f"  Müqayisə cəmi: {assessed.amount} {assessed.currency} ({assessed.basis})"
        )
        self.stdout.write(f"  PO: {po.code} → {po.get_status_display()}")
        self.stdout.write("  Anbar (əvvəl → indi):")
        for code, sku, qty in sku_rows:
            stock = Stock.objects.filter(sku=sku, warehouse=wh).first()
            now_q = stock.quantity if stock else Decimal("0")
            self.stdout.write(
                f"    {code} {sku.name}: {before_qty[code]} → {now_q} (+{qty} {sku.unit})"
            )
        self.stdout.write("")
        self.stdout.write("ERP baxış:")
        self.stdout.write("  /erp/procurement/suppliers/")
        self.stdout.write(f"  /erp/procurement/prs/{pr.code}/")
        self.stdout.write(f"  /erp/procurement/rfqs/{rfq.code}/")
        self.stdout.write(f"  /erp/procurement/pos/{po.code}/")
        self.stdout.write("  /erp/warehouse/")

    def _ensure_suppliers(self) -> list[Party]:
        out = []
        for tax_id, legal, brand, email, phone in SUPPLIERS:
            party, created = Party.objects.get_or_create(
                tax_id=tax_id,
                defaults={
                    "party_type": PartyType.ORGANIZATION,
                    "legal_name": legal,
                    "brand_name": brand,
                    "status": PartyStatus.ACTIVE,
                    "contact_email": email,
                    "contact_phone": phone,
                    "notes": f"{DEMO_TAG} demo podratçı",
                },
            )
            if not created:
                party.legal_name = legal
                party.brand_name = brand
                party.status = PartyStatus.ACTIVE
                party.contact_email = email
                party.contact_phone = phone
                party.save(
                    update_fields=[
                        "legal_name",
                        "brand_name",
                        "status",
                        "contact_email",
                        "contact_phone",
                    ]
                )
            PartyRole.objects.get_or_create(
                party=party, role=PartyRoleCode.SUPPLIER, defaults={"is_primary": True}
            )
            out.append(party)
            self.stdout.write(f"  Podratçı: {party.display_name}")
        return out

    def _ensure_warehouse_skus(self):
        wh, _ = Warehouse.objects.get_or_create(
            code="MAIN", defaults={"name": "Əsas anbar"}
        )
        rows = []
        for code, name, unit, reorder, order_qty in SKUS:
            sku, _ = SKU.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "unit": unit,
                    "reorder_level": Decimal(reorder),
                },
            )
            Stock.objects.get_or_create(
                sku=sku,
                warehouse=wh,
                bin=None,
                defaults={"quantity": Decimal("2"), "reserved_quantity": Decimal("0")},
            )
            rows.append((code, sku, Decimal(order_qty)))
        return wh, rows

    def _print_summary(self, pr: PurchaseRequest) -> None:
        self.stdout.write(f"  PR: {pr.code} · {pr.get_status_display()}")
        for po in pr.purchase_orders.all():
            self.stdout.write(f"  PO: {po.code} · {po.get_status_display()}")
        self.stdout.write("  /erp/procurement/ · /erp/warehouse/")
