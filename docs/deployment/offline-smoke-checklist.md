# Offline / LAN smoke checklist — results

**Date:** 2026-09-21  
**Environment:** `bin/dev` Docker (host :3001)  
**Goal:** App usable without Internet CDN / public SaaS.

Legend: PASS / FAIL / N/A (ops on production host)

---

## A. Static & UI (no CDN)

| # | Check | Result | Evidence |
|---|--------|--------|----------|
| A1 | No `fonts.googleapis` / `unpkg` / jsDelivr in templates | **PASS** | ripgrep: zero matches |
| A2 | `static/vendor/lucide.min.js` present | **PASS** | file on disk |
| A3 | `/static/vendor/lucide.min.js` → 200 | **PASS** | Django client |
| A4 | `/static/css/cp.css` → 200 | **PASS** | Django client |
| A5 | `/login/` HTML has local lucide, no CDN | **PASS** | `vendor/lucide`, `cdn_in_login=none` |
| A6 | System font stack (no Google Fonts) | **PASS** | `cp.css` → `system-ui…` |

## B. Surfaces (authenticated)

| # | Check | Result | Evidence |
|---|--------|--------|----------|
| B1 | `/erp/` as admin | **PASS** | 200, no CDN |
| B2 | `/portal/` as resident | **PASS** | 200, no CDN |
| B3 | `/security/` as security | **PASS** | 200, no CDN |

## C. Integrations (LAN)

| # | Check | Result | Notes |
|---|--------|--------|-------|
| C1 | AxTrax health API callable without Internet | **PASS** | `axtrax_sync_health()` runs |
| C2 | Events sync fresh (<30 min) | **FAIL*** | `events_ok=False` — start poller on LAN host |
| C3 | Postgres up | **PASS** | compose healthy |

\*Not an Internet issue — poller not running in this session.

## D. Offline mail policy (prod config)

| # | Check | Result | Notes |
|---|--------|--------|-------|
| D1 | `CP_OFFLINE=1` documented in prod `.env.example` | **PASS** | `bin/prod/.env.example` |
| D2 | Dev currently `CP_OFFLINE=False` | **N/A** | Expected for local DEBUG |
| D3 | File outbox path when offline | **PASS** | settings: `var/mail_outbox` when `CP_OFFLINE=1` |

## E. Production host drills (do on go-live machine)

| # | Check | Result |
|---|--------|--------|
| E1 | Unplug Internet uplink; keep LAN; open Portal/ERP | **TODO** (site) |
| E2 | `CP_OFFLINE=1` in prod `.env` | **TODO** |
| E3 | AxTrax poller Scheduled Task | **TODO** — `bin/prod/register_axtrax_poller_task.ps1` |
| E4 | Invite via copied LAN URL (no external SMTP) | **TODO** |
| E5 | Backup to local NAS + restore drill | **TODO** |
| E6 | Docker images pre-loaded (`docker load`) | **TODO** |

---

## Verdict

**Dev smoke (CDN/offline UI): PASS.**  
**Go-live ops (E1–E6 + AxTrax poller): still TODO on the building server.**

Reference: [air-gapped-lan.md](./air-gapped-lan.md)
