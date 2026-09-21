# Architecture documentation index

City Point ERP follows the **Final Master Implementation Plan** (Phases 0–13).

## Phase 0 audit (current)

Start here: **[phase0-README.md](./phase0-README.md)** — ten audit artifacts, preserve/extend/migrate decisions, next = Phase 1.

## Documents in this folder

| Doc | Purpose |
|-----|---------|
| [phase0-README.md](./phase0-README.md) | Phase 0 audit index + decisions |
| [phase2-erp-core.md](./phase2-erp-core.md) | Phase 2 ERP Core deliverables |
| [legacy-mapping.md](./legacy-mapping.md) | Current MVP models ↔ target domain mapping |
| [party-space-lease-model.md](./party-space-lease-model.md) | Proposed Party / Space / Lease model (approval checkpoint) |
| [api-standards.md](./api-standards.md) | Public / Resident / Internal / Integration API rules |
| [../integrations/website-contract.md](../integrations/website-contract.md) | Website ↔ ERP contract (stub until real website schema) |
| [../integrations/turnstile-audit.md](../integrations/turnstile-audit.md) | Turnstile vendor audit checklist (no guessing) |

## Principles

1. **Single Source of Truth** — one owning module per entity.
2. **No rewrite of working MVP** without mapping + migration plan.
3. **Domain logic in services**, not templates/views.
4. **DO NOT GUESS** external schemas (turnstile, website, accounting).
5. Next phase starts only after previous acceptance + regression.
6. Scaffold UI is never marketed as production-complete.
