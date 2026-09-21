# Phase 2 — ERP Core

## Delivered

| Area | Implementation |
|------|----------------|
| Domain events | `apps/core/events.py` + handlers → AuditLog |
| Wired events | TicketCreated, VisitorCheckedIn/Out, LeaseActivated/Terminated, Approval* |
| Organization | `Organization`, `OrgDepartment`, `OrgQueue`, `Team` (+ seed from ticket depts) |
| Party dual-read | `apps/parties/resolvers.py` (`party_for_company`, `person_for_employee`) |
| Approval engine | `ApprovalService` in `apps/workflows/services.py` |
| Email helper | `apps/comms/mail.py` `send_templated_email` |
| RBAC | + lease.*, approval.*, security.view |
| CRM handoff fix | uses `party_for_company` (was broken `Party.name`) |

## Preserve

TicketDepartment/TicketQueue remain routing SoT; org tree is parallel until a later FK link.

## Commands

```bash
python manage.py sync_parties   # Party/Person + RBAC + Organization seed
```

## Tests

`apps.core.tests.test_phase2_core`

## Not in this phase (later)

- Big-bang Resident → Party cutover
- Full notification worker / SMS
- TicketDepartment FK → OrgDepartment
- Celery / async event bus
