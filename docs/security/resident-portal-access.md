# Resident Portal access (external tenants)

Residents are usually **outside** City Point LAN. They receive only the **Resident Portal**, never staff ERP or direct database access.

## Exposure model

| Surface | Audience | Exposure |
|---------|----------|----------|
| Resident Portal (`/portal/`) | Tenant office users | Public HTTPS (e.g. `portal.citypoint.az`) |
| Security Portal (`/security/`) | Security staff (+ admin/management) | Internal / office network preferred |
| Staff ERP (`/erp/`) | Reception, Desk, FM, Management | VPN / office allowlist / internal host preferred |
| Django Admin | Admins | Internal only |
| PostgreSQL `:5432` | App servers only | Never public |
| AxTrax MS SQL | Sync poller only | Private; read-only |

Same Django app may serve both paths; in production prefer separate hostnames / reverse-proxy rules so Portal host cannot reach ERP paths, and `resident_user` is denied ERP in application code (`StaffRequiredMixin`).

## Account provisioning (no public signup)

1. City Point Admin creates `User` with `role=resident_user` and `resident_company` set.
2. System issues a **one-time invite** (email link); user sets their own password.
3. Optional later: company-admin invites colleagues; Microsoft 365 SSO for large tenants.

**Do not:** open self-registration, or send long-lived shared passwords over WhatsApp.

Turnstile badge holders (`ResidentEmployee`) are **not** automatically Portal logins. Typical tenant needs one or few portal accounts (office manager).

## Runtime behaviour (implemented)

- `must_set_password` forces password set after invite / admin reset.
- Invite token URL: `/accounts/invite/<token>/`
- Forgot password: `/accounts/password-reset/`
- Management command: `invite_portal_user`

## Security notes for Portal on the internet

- TLS + HSTS; `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` when HTTPS
- Rate-limit login and reset endpoints at the reverse proxy
- Tenant isolation: all portal queries filter by `request.user.resident_company`
