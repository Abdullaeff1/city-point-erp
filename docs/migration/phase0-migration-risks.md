# Phase 0.8 — Migration Risk Report

| Area | Risk | Why | Mitigation |
|------|------|-----|------------|
| Party / Person cutover | **High** | Portal, tickets, access, AxTrax ExternalIdentity point at Resident* | Link FK first; dual-read; freeze window; never delete Resident* until AccessEvent PROTECT cleared |
| ResidentEmployee soft-delete | **Medium** | AxTrax missing → deactivate; history must remain | Keep PROTECT on AccessEvent; archive roster UI already |
| Space.resident vs Lease | **Medium** | Occupancy can disagree | Lease activate/terminate already cascades; Phase 3 make Lease authoritative |
| AxTrax ExternalIdentity | **Medium** | `emp:` / `event:` keys; cursor SyncLog | Never renumber PKs casually; export identity map before cutover |
| Lease activate | **Medium** | Side effects on spaces/portal | Test cascade; audit log |
| Ticket relations | **Low–Med** | Company FK, subcategory routing | Preserve PKs; taxonomy seed idempotent |
| Document attachments | **Medium** | Metadata without files; DocumentVersion unused | Migrate files deliberately; don’t invent paths |
| Card-order tickets | **Low** | related_employee FK | Keep through employee Person migration via bridge |
| Guest / visitor history | **Low** | Reception models stable | Additive only |
| Destructive prod migrate | **Critical if done** | — | Backup + restore drill required before any cutover |

## Rules

1. Migrations must be reversible where practical; always backup first.
2. No big-bang Resident → Party replace in one deploy.
3. Idempotent data scripts (`sync_parties`, taxonomy seed) preferred.
4. AxTrax cursor must not reset without explicit ops decision (would skip or reprocess events).
