# Architecture documentation index

City Point ERP follows the **Master Implementation Plan** (Scope 0–12).

## Documents in this folder

| Doc | Purpose |
|-----|---------|
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
5. Next scope starts only after previous acceptance + regression.
