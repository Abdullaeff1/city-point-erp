# M8 — Anbar və Satınalma

**Status:** icra olunub (2026-11-18)  
**Defer:** tam RFQ UI, invoice ↔ PO UI e2e (M10), Party cutover

---

## 1. Anbar

| Maddə | Kod |
|-------|-----|
| SKU / unit / warehouse / bin / reorder | `SKU`, `Warehouse`, `Bin`, `Stock` |
| Mövcud / rezerv | `quantity`, `reserved_quantity`, `available_quantity` |
| Hərəkətlər (dəyişməz) | `StockMovement` + `apply_movement` |
| WO → rezerv → təsdiq → ISSUE | `request_issue_line` / `confirm_issue` |

---

## 2. Satınalma

| Maddə | Kod |
|-------|-----|
| Low stock → PR (təkrarsız) | `create_pr_from_low_stock` |
| PR → approve (limit) → PO | `approve_pr` / `PurchaseApprovalLimit` |
| RFQ + quote müqayisə | `RFQ` / `RFQQuote` / `select_rfq_quote_and_create_po` |
| Qismən/tam qəbul | `receive_po(..., line_qtys=)` → PARTIAL/RECEIVED |
| Təchizatçı | `PurchaseOrder.supplier_party` → Party |

---

## 3. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M8-1 | Reservation / available | test |
| M8-2 | Duplicate low-stock PR | test |
| M8-3 | Partial receive | test |
| M8-4 | WO issue confirm | mövcud + rezerv |

UAT operator Pass ayrıca.
