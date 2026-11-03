# Ticket routing repair (Security / Service Desk portals)

## Problem

Resident portal tickets (e.g. ASBC) chosen as **Təhlükəsizlik** or **Texniki** may not appear in Security / Service Desk portals on the server.

**Passwords are unrelated.** Visibility is:

1. On create, `route_ticket()` sets `ticket.department` from `RoutingRule` on the **subcategory** (not category alone).
2. Staff lists use `tickets_visible_to(user)` → `ticket.department_id == user.ticket_department_id`.

If `RoutingRule` is missing/wrong, or `User.ticket_department` is empty on `security@` / `desk@`, tickets look “lost”.

## After deploying this update

```bash
python manage.py migrate
python manage.py repair_ticket_routing
# optional preview first:
python manage.py repair_ticket_routing --dry-run
```

This command:

- Re-seeds taxonomy + routing rules
- Sets `ticket_department` from role (`security` → security, `service_desk` → servicedesk)
- Re-routes open tickets whose department does not match the subcategory rule (or is NULL)

## Code hardening in this release

- Category → default queue/department **fallback** when a rule is missing
- Role default department for ACL when `ticket_department` is blank
- Portal create fails loudly if a ticket still has no department
