# Architecture documentation index

City Point ERP follows the **Final Master Implementation Plan** (Phases 0–13).

## Target-state technical plan (all modules)

**[CityPoint_Tam_Texniki_Plan.md](./CityPoint_Tam_Texniki_Plan.md)** — tam hədəf texniki plan: bütün modullar, arxitektura, NFR, deploy, risklər, **xərclər** (CAPEX/OPEX).

## Phase 0 audit (current)

Start here: **[phase0-README.md](./phase0-README.md)** — ten audit artifacts, preserve/extend/migrate decisions, next = Phase 1.

**Full-system refresh (2026-11-27):** [system-architecture-audit-2026-11-27.md](./system-architecture-audit-2026-11-27.md) — modules, routes, RBAC, Supply/AP deltas, debts, recommended sequence (read-only).

## Department architecture (Phase 1)

**[department-based-architecture-blueprint.md](./department-based-architecture-blueprint.md)** — nine departments mapped to roles/portals/shared domains; RBAC/nav/dashboard roadmap; no duplicate entities.

## Documents in this folder

| Doc | Purpose |
|-----|---------|
| [CityPoint_Tam_Texniki_Plan.md](./CityPoint_Tam_Texniki_Plan.md) | Tam bitmiş sistem texniki planı + xərc |
| [department-based-architecture-blueprint.md](./department-based-architecture-blueprint.md) | Phase 1 dept architecture blueprint |
| [phase0-README.md](./phase0-README.md) | Phase 0 audit index + decisions |
| [phase-gaps-and-open-questions.md](./phase-gaps-and-open-questions.md) | M1–M12 boşluqlar + P0–P3 cavab gözləyənlər |
| [finish-requirements.md](./finish-requirements.md) | Production üçün lazım olan biznes/ops məlumat |
| [phase2-erp-core.md](./phase2-erp-core.md) | Phase 2 ERP Core deliverables |
| [legacy-mapping.md](./legacy-mapping.md) | Current MVP models ↔ target domain mapping |
| [party-space-lease-model.md](./party-space-lease-model.md) | Proposed Party / Space / Lease model (approval checkpoint) |
| [api-standards.md](./api-standards.md) | Public / Resident / Internal / Integration API rules |
| [../integrations/website-contract.md](../integrations/website-contract.md) | Website ↔ ERP contract (stub until real website schema) |
| [../integrations/turnstile-audit.md](../integrations/turnstile-audit.md) | Turnstile vendor audit checklist (no guessing) |

## Pilot / UAT trackers (ops doldurur)

| Doc | Purpose |
|-----|---------|
| [../uat/crm-written-acceptance.md](../uat/crm-written-acceptance.md) | Satış CRM yazılı qəbul (A7) |
| [../uat/functional-readiness-checklist.md](../uat/functional-readiness-checklist.md) | UAT §A–E |
| [../uat/coa-import-uat.md](../uat/coa-import-uat.md) | Real CoA + TB UAT (M10) |
| [../uat/workflow-a-qonaq-live-acceptance.md](../uat/workflow-a-qonaq-live-acceptance.md) | Workflow A canlı QONAQ qəbul vərəqi |
| [../ops/p0-go-live-answers.md](../ops/p0-go-live-answers.md) | P0 mail / LAN / pilot / AxTrax RO |
| [../deployment/netadmin-handoff-checklist.md](../deployment/netadmin-handoff-checklist.md) | NetAdmin 9 tapşırıq |

## Principles

1. **Single Source of Truth** — one owning module per entity.
2. **No rewrite of working MVP** without mapping + migration plan.
3. **Domain logic in services**, not templates/views.
4. **DO NOT GUESS** external schemas (turnstile, website, accounting).
5. Next phase starts only after previous acceptance + regression.
6. Scaffold UI is never marketed as production-complete.
