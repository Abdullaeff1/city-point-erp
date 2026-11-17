# M5 — Portal, Reception, əməkdaşlar

**Status:** icra olunub (2026-11-17)  
**Defer:** AxTrax write, Party cutover, NetAdmin, real turnstile

---

## 1. Reception enforcement (P0)

| Qayda | Kod |
|-------|-----|
| ID held → seriya + qonaq kartı | `register_walk_in` / `check_in_visit` |
| ID held deyil → `override_id` + səbəb | eyni (kuryer + guest-list istisna) |
| `no_show` | `reception.cancel_visit` icazəsi |
| Portal pre-reg host | `host.is_active` |

---

## 2. Əməkdaş (P1)

| Maddə | Nəticə |
|-------|--------|
| ERP deaktiv | Admin/Management → employee detail POST `deactivate` |
| AxTrax name link | Eyni adda ≥2 unlinked → skip (ambiguity) |

---

## 3. Qəbul

| # | Meyar | Pass |
|---|--------|------|
| M5-1 | Check-in seriya when ID held | test |
| M5-2 | Override path | walk-in / check-in |
| M5-3 | no_show RBAC | ERP view |
| M5-4 | Inactive host blocked | pre_register |
| M5-5 | Employee deactivate | service + ERP |
| M5-6 | Name match safety | axtrax helper |

UAT §C operator Pass ayrıca qalır.
