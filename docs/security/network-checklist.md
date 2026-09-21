# Network & host checklist (prod)

**Default go-live model:** City Point **LAN / air-gapped** (see [../deployment/air-gapped-lan.md](../deployment/air-gapped-lan.md)).  
Public Internet for Portal is **optional later**, not assumed.

## Must (LAN go-live)

- [ ] PostgreSQL listens only on private network / Docker network; **no public `5432`**
- [ ] Firewall: app → Postgres allow; world → Postgres deny
- [ ] AxTrax MS SQL (`AxTrax1`) reachable only from sync host; login **SELECT-only** on approved tables
- [ ] Secrets in env/secret store — not in git (`.env` gitignored)
- [ ] Encrypted **local/NAS** backups; restore tested; backup credentials ≠ `cp_app`
- [ ] `DJANGO_DEBUG=0`, strong `DJANGO_SECRET_KEY`, explicit `DJANGO_ALLOWED_HOSTS` / CSRF origins (LAN names/IPs)
- [ ] `CP_OFFLINE=1` when no Internet; no CDN dependencies (static vendor assets)
- [ ] UI works with Internet uplink **disconnected** (smoke test)
- [ ] AxTrax poller as Scheduled Task on LAN sync host

## Should (LAN)

- [ ] Internal DNS or hosts file: `portal.citypoint.local` / `erp.citypoint.local`
- [ ] Staff ERP only on office VLAN; residents only Portal VLAN if segmented
- [ ] Rate limit `/login/`, password-reset, invite on the LAN proxy if available
- [ ] Internal NTP (domain controller)

## Optional later (if public Internet is ever added)

- [ ] Portal HTTPS + public hostname
- [ ] Hostname split: public Portal vs VPN-only ERP
- [ ] Proxy blocks `/erp/` and `/admin/` on public vhost
- [ ] HSTS / secure cookies behind TLS proxy

## AxTrax sync host

- [ ] Poller machine has RO credentials only
- [ ] No write grants on AxTrax
- [ ] Sync writes only into City Point Postgres via app/migrate path

## Out of scope (do not open)

- Direct resident access to Postgres or AxTrax
- Public Django Admin
- Shared production passwords in chat
- Runtime dependency on Google Fonts / unpkg / public SMTP / Docker Hub

Related: [resident-portal-access.md](resident-portal-access.md), [database-isolation.md](database-isolation.md), [../deployment/air-gapped-lan.md](../deployment/air-gapped-lan.md).
