# AxTrax RO poller — DoD status (2026-11-27)

**Qərar:** ERP → AxTrax **yazma yoxdur**. DoD = **oxu-only** people/events sync + poller 24/7.

Runbook: [../integrations/axtrax-poller-runbook.md](../integrations/axtrax-poller-runbook.md) · LAN: [../deployment/teammate-axtrax-lan.md](../deployment/teammate-axtrax-lan.md) · P0 forma: [p0-go-live-answers.md](p0-go-live-answers.md) §P0.6

---

## Engineering checklist

| # | Maddə | Status | Sübut |
|---|-------|--------|-------|
| 1 | `poll_axtrax` / in-container poller (`AXTRAX_POLL_ON_START`) | **İşləyir** | `var/axtrax_poller.log` — «AxTrax poller started interval=15s» |
| 2 | RO credentials env (`TURNSTILE_MSSQL_*`) | **Təyin olunub** (dev `.env`) | Parol git-ə yazılmır |
| 3 | `axtrax_sync_status` CLI | **OK** | Aşağıdakı snapshot |
| 4 | Host `172.31.104.10:1433` bu Docker hostundan | **Blocked** | TDS `Connection timed out (110)` |
| 5 | `events_ok` / təzə sync | **Stale** | Son uğurlu sync ~2026-11-25 |
| 6 | Prod supervizor (Task Scheduler / systemd) | **Ops açıq** | P0.6 forma boş |
| 7 | Health monitoring (dashboard sync card) | **Kod hazır** | LAN olanda yaşıl olacaq |

### `axtrax_sync_status` (2026-11-27, lokal Docker)

```text
events_ok=False stale=True
cursor=32972350
last_event_sync_at=2026-11-25 11:28:25.455861+00:00
last_people_sync_at=2026-11-25 10:43:33.327500+00:00
last_access_event_at=2026-11-25 11:27:43+00:00
last_error_at=None
```

### Poller log (nümunə)

```text
AxTrax poller started interval=15s lookback=48h people_every=300s
AxTrax poll error: ... Unable to connect: TDS server is unavailable or does not exist (172.31.104.10)
Net-Lib error during Connection timed out (110)
```

---

## NetAdmin / Ops — bağlamaq üçün

1. Notebook/server **City Point LAN**-a (AxTrax VLAN) qoşulsun.
2. `Test-NetConnection 172.31.104.10 -Port 1433` → `TcpTestSucceeded : True`.
3. Firewall: RO user + source IP icazəsi.
4. [p0-go-live-answers.md](p0-go-live-answers.md) P0.6 cədvəlini doldurun (host, DB, RO user, poller maşını, supervizor).
5. Poller restart; `axtrax_sync_status` → `events_ok=True`, `stale=False`.
6. Security day view — canlı AccessEvent ilə müqayisə (UAT §C C3).

**Engineering DoD (kod + poller prosesi):** bağlandı.  
**Production RO DoD (şəbəkə + credentials + 24/7 host):** NetAdmin — açıq (yuxarı addımlar).
