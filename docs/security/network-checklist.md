# Network & host checklist (prod)

## Must

- [ ] PostgreSQL listens only on private network / Docker network; **no public `5432`**
- [ ] Firewall: app → Postgres allow; world → Postgres deny
- [ ] AxTrax MS SQL (`AxTrax1`) reachable only from sync host; login **SELECT-only** on approved tables
- [ ] Secrets in env/secret store — not in git (`.env` gitignored)
- [ ] Encrypted backups; restore tested quarterly; backup credentials ≠ `cp_app`
- [ ] Portal served over **HTTPS** with valid certificate
- [ ] `DJANGO_DEBUG=0`, strong `DJANGO_SECRET_KEY`, explicit `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS`

## Should

- [ ] Hostname split: `portal.…` (public) vs `erp.…` (VPN / office IP allowlist)
- [ ] Reverse proxy blocks `/erp/` and `/admin/` on the public Portal vhost
- [ ] Rate limit `/login/`, `/accounts/password-reset/`, `/accounts/invite/`
- [ ] WAF or fail2ban on public edge
- [ ] Staff ERP only on VPN or corporate network
- [ ] HSTS and secure cookies when TLS terminates at proxy (`SECURE_PROXY_SSL_HEADER` if needed)

## AxTrax sync host

- [ ] Poller machine has RO credentials only
- [ ] No write grants on AxTrax
- [ ] Sync writes only into City Point Postgres via app/migrate path

## Out of scope (do not open)

- Direct resident access to Postgres or AxTrax
- Public Django Admin
- Shared production passwords in chat

Related: [resident-portal-access.md](resident-portal-access.md), [database-isolation.md](database-isolation.md).
