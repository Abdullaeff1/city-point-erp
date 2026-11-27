# M5 — Portal, Reception, əməkdaşlar

**Status:** icra olunub (2026-11-18) · UAT §C engineering Pass 2026-11-27  
**Defer:** Party cutover, NetAdmin RO LAN/TLS. ~~AxTrax write / turnstile write-back~~ — **məhsul qərarı ilə scope-dan çıxarılıb** (oxu-only kifayət).

---

## 1. Reception (P0/P1)

| Qayda | Kod |
|-------|-----|
| ID held → seriya məcburi; **qonaq kartı ayrıca / istəyə bağlı** | `register_walk_in` / `check_in_visit` / `update_visit_details` |
| Kart verildikdə credential + ACTIVE `VisitorAccess` | `create_visitor_access` |
| ID held deyil → `override_id` + səbəb | eyni (kuryer + guest-list istisna) |
| Kartlı qonaq çıxışı → AccessEvent OUT | `checkout_guests_from_access_events` (AxTrax sync hook) |
| Kartı olmayan Inside → portal «Çıxış ver» | `can_portal_checkout` / `portal_check_out_visit` |
| `no_show` | `reception.cancel_visit` icazəsi |
| Portal pre-reg host | `host.is_active` |

---

## 2. Portal qonaq tarixçəsi

| Maddə | Nəticə |
|-------|--------|
| 7 / 30 / 90 gün + from/to | `GuestsView` + `portal/guests.html` |
| Scope (single / all) | mövcud `portal_company_ids` |

---

## 3. Əməkdaş / AxTrax read-only

| Maddə | Nəticə |
|-------|--------|
| Kart səviyyəsi ERP-də əl ilə dəyişilmir | Admin `readonly_fields`: `access_level`, `card_number` |
| UI label | ERP əməkdaş cədvəli — AxTrax mənbəyi |
| Sifariş formunda «istənilən səviyyə» | Portal card-order (request); faktiki səviyyə sync-dən |
| ERP deaktiv | employee detail POST `deactivate` |
| AxTrax name link safety | ambiguity skip |

---

## 4. Qəbul meyarları

| # | Meyar | Pass |
|---|--------|------|
| M5-1 | Check-in seriya when ID held | test |
| M5-2 | ID without card OK; card optional | test |
| M5-3 | Override path | walk-in / check-in |
| M5-4 | AccessEvent OUT → guest checkout | test + sync hook |
| M5-5 | Portal date filter | UI + view |
| M5-6 | access_level readonly (admin) | admin |
| M5-7 | Inactive host blocked | pre_register |
| M5-8 | Employee deactivate | service + ERP |

UAT §C operator Pass ayrıca qalır.
