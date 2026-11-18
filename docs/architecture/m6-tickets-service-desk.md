# M6 — Service Desk və Ticket

**Status:** icra olunub (2026-11-18)  
**Defer:** warehouse material e2e (Phase 7–8), Party cutover, NetAdmin

---

## 1. Axın

Portal/ERP create → `route_ticket` (RoutingRule DB) → dept/queue/assignee → status/SLA/waiting → əl ilə WO/CRM.

---

## 2. Todoist meyarları

| Maddə | Nəticə |
|-------|--------|
| Type → Category → Subcategory | `seed_ticket_taxonomy` + `taxonomy_map` |
| Reception qonaq ≠ ticket | taxonomy-də guest/reception yoxdur |
| RoutingRule idarə olunan | `RoutingRule` model + admin |
| Dept → Queue → Assignee | `route_ticket` / `assign_ticket_employee` / handoff |
| Status keçidləri | `can_transition_to` + `STATUS_FLOW` |
| Gözləmədə səbəb + SLA pause | `waiting_reason_code` / `pause_sla` |
| SLA + eskalasiya | business calendar + `poll_ticket_sla_escalations` |
| Mesaj/fayl/tarixçə ACL | `can_mutate_ticket` / dept access |
| WO yalnız uyğun kateqoriya | `wo_eligible` (texniki + yanğın); service enforce |
| Kommersiya → CRM | `create_opportunity_from_ticket` (əl ilə) |
| Portal status/cavab | `portal/request_detail` |

---

## 3. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M6-1 | Taxonomy + routing seed | test |
| M6-2 | Waiting SLA pause | test |
| M6-3 | Escalation / CRM | test |
| M6-4 | WO eligibility gate | test |
| M6-5 | Portal detail status/messages | UI |

UAT §C operator Pass ayrıca.
