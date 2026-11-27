# UAT §C Daily ops — engineering Pass (2026-11-27)

**Məqsəd:** Portal / Reception / Ticket→WO axınları üçün operator Pass-ə hazırlıq sübutu.  
**AxTrax write:** tələb olunmur (məhsul qərarı 2026-11-18) — kart sifarişi ERP daxilində qalır.

| Sahə | Dəyər |
|------|--------|
| Git | `d3907d7` (+ seed desk dept düzəlişi) |
| Mühit | Docker `http://127.0.0.1:3001` |
| Demo | `office@asbc.az` / `asbc123` · `reception@citypoint.az` / `reception123` · `desk@citypoint.az` / `desk123` |

---

## C1 — Portal card order

| Meyar | Nəticə | Sübut |
|-------|--------|-------|
| Label/placeholder **Ad Soyad Ata adı** | **Pass** | Brauzer: `/portal/requests/new/?intent=card_order` |
| Security kateqoriya + kart alt kateqoriya prefill | **Pass** | Eyni forma |
| Employee + Security ticket (unit) | **Pass** | `apps.residents.tests.test_card_order` · `apps.portal.tests.test_portal_readiness` |

Screenshot: `artifacts/uat-section-c/uat-c-portal-card-order.png` (Playwright run)

---

## C2 — Reception check-in / check-out

| Meyar | Nəticə | Sübut |
|-------|--------|-------|
| Reception UI açılır (`/erp/reception/`) | **Pass** | Brauzer · `artifacts/uat-section-c/uat-c-reception-desk.png` |
| Check-in / check-out / ID held / OUT→checkout | **Pass** | `apps.reception.tests` + `apps.reception.tests_workflow_a` — **54 OK** |
| AxTrax write / turnstile grant | **N/A** | Scope-dan çıxarılıb |

---

## C3 — Security / AxTrax events (oxu)

| Meyar | Nəticə | Qeyd |
|-------|--------|------|
| Kod: AccessEvent sync + people RO | **Hazır** | Poller + `axtrax_sync_status` |
| Canlı LAN hadisələri bu mühitdə | **Blocked** | `172.31.104.10:1433` TDS timeout — bax [axtrax-ro-dod-status-2026-11-27.md](../ops/axtrax-ro-dod-status-2026-11-27.md) |

---

## C4 — Ticket → assign → WO

| Meyar | Nəticə | Sübut |
|-------|--------|-------|
| `create_work_order_from_ticket` / WO UI | **Pass** | `apps.tickets.tests.test_workflow_b` **9 OK** · `WorkOrderRestoreTests.test_service_desk_creates_work_order_without_moving_the_ticket` **OK** |
| Brauzer: TK-1040 → **WO-1106** | **Pass** | Desk: «İş sifarişi yarat» → `/erp/work-orders/WO-1106/` |
| Seed: desk `ticket_department` | **Düzəldildi** | `webservis` → `servicedesk` (`seed_demo.py`) — əks halda desk növbəsi boş qalırdı |

Screenshot: `artifacts/uat-section-c/uat-c-ticket-to-wo.png`

---

## Avtomat suite (bu qaçış)

```text
apps.residents.tests.test_card_order + portal_readiness + security card_order +
tickets escalation/crm + workflow_b + deferred_notify  → 39/40 OK
  (1 ERROR = yanlış test class adı; deferred_notify modulu ayrıca OK)
apps.reception.tests + tests_workflow_a                 → 54 OK
apps.tickets.tests.test_workflow_b                      → 9 OK
ticket→WO UI unit                                       → 1 OK
```

---

## Operator imza (Ops)

Engineering Pass **yuxarıdakı** sübutlarla bağlanır. Formal operator checkbox üçün:

| §C sətir | Ops Pass | Tarix | İmza |
|----------|----------|-------|------|
| C1 Portal card order | ☐ | | |
| C2 Reception in/out | ☐ | | |
| C3 AxTrax RO day view (LAN) | ☐ | | (NetAdmin + RO DoD) |
| C4 Ticket→WO | ☐ | | |

Tracker: [functional-readiness-checklist.md](functional-readiness-checklist.md) §C.
