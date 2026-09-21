# Phase 0.1 — Current Architecture Map

## Surfaces (URL faces)

| Surface | Mount | App shell | Access gate |
|---------|-------|-----------|-------------|
| Login / accounts | `/login/`, `/accounts/` | `apps.accounts` | Public auth |
| Resident Portal | `/portal/` | `apps.portal` + templates | `ResidentPortalMixin` |
| Staff ERP | `/erp/` | `apps.erp` + templates | `StaffRequiredMixin` / `RoleRequiredMixin` |
| Security | `/security/` | `apps.security` + templates | `SecurityPortalMixin` |
| Django Admin | `/admin/` | Django | Staff/superuser |
| API | `/api/` | `apps.api` | Mixed (public stubs + reception staff) |

Root: [`config/urls.py`](../../config/urls.py).

## Installed Django apps

From [`config/settings.py`](../../config/settings.py):

`core`, `accounts`, `parties`, `property`, `residents`, `reception`, `tickets`, `comms`, `documents`, `audit`, `rbac`, `workflows`, `integrations`, `leases`, `crm`, `maintenance`, `warehouse`, `procurement`, `billing`, `accounting`, `api`, `portal`, `security`, `erp`.

**Note:** There is no separate `access_control` app yet. Access events and alerts live under `residents`.

## Authentication & roles

- Custom user: `accounts.User` (`AUTH_USER_MODEL`), email as username.
- Roles: `admin`, `management`, `reception`, `service_desk`, `property_fm`, `security`, `resident_user`.
- ERP: staff except security (`can_access_erp`).
- Security portal: security + admin + management.
- Portal: resident_user (with company) or staff; security blocked.
- Middleware: `MustSetPasswordMiddleware` forces password set after invite.

## RBAC

- Coarse: role CharField on User + mixins.
- Fine (foundation): `rbac.PermissionCode`, `rbac.RolePermission` — not fully wired into every view.
- Nav visibility: `apps.accounts.context_processors.role_context`.

## Service / domain entry points (selected)

| Domain | Primary services |
|--------|------------------|
| Reception | `apps.reception.services` |
| Tickets | `apps.tickets.services` (+ `seed_taxonomy`) |
| Residents / card order | `apps.residents.services`, `access.py`, `rapid_swipe.py`, `shaft_access.py` |
| Leases | `apps.leases.services` |
| CRM | `apps.crm.services` |
| Maintenance | `apps.maintenance.services` |
| Warehouse | `apps.warehouse.services` |
| Billing | `apps.billing.services` |
| Parties | `apps.parties.services` |
| Audit | `apps.audit.services` |
| Comms | `apps.comms.services` |
| Integrations | `axtrax_people_sync`, `axtrax_events_sync`, `adapters` |

## Integration entry points

- CLI: `sync_axtrax_people`, `sync_axtrax_events`, `export_access_year`
- Host scripts: `bin/dev/export_axtrax_people.ps1`, `bin/dev/poll_axtrax_events.ps1`
- Adapters: `MockAccessControlAdapter`, `MockWebsiteLeadAdapter`
- Identity map: `integrations.ExternalIdentity` + `SyncLog`

## Frontend

- Server-rendered Django templates under `templates/{portal,erp,security,accounts}/`
- Shared CSS: `static/css/cp.css`
- No SPA frontend

## Runtime

- Dev: Docker Compose `bin/dev` (host :3001 → web :8000)
- Prod skeleton: `bin/prod/`
- DB: PostgreSQL; AxTrax: external MS SQL (read-only, not ERP DB)
