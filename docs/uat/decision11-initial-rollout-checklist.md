# Decision 11 — İlkin əməliyyat qəbulu (lokal)

**Tarix:** 2026-11-27  
**Məhsul:** cari sistem = hədəf məhsul. Prioritet: Reception, Security, Tickets, Resident Portal (+ asılılıqlar).  
**Qadağa:** bu tapşırıqda demo/tarixi data silinmir, DB reset, media purge, prod resident seçimi və deploy yoxdur.

## A. Reception

| # | Ssenari | Pass? | Qeyd |
|---|---------|-------|------|
| R1 | Əvvəlcədən qeydiyyat (portal) → Reception gözləyən | ☐ | |
| R2 | Walk-in + ID held + seriya | ☐ | |
| R3 | Kartlı qonaq (opsional) — Reception-owned checkout | ☐ | |
| R4 | Fiziki vəsiqə qaytarılması (`complete_id_return` / checkout + id_returned) | ☐ | |
| R5 | 24s+ INSIDE + ID held → Reception bildirişi + `?status=inside_overdue` | ☐ | D07 |

## B. Security

| # | Ssenari | Pass? | Qeyd |
|---|---------|-------|------|
| S1 | Səlahiyyətli qonaq jurnalı / görünürlük | ☐ | |
| S2 | AccessEvent (AxTrax RO) sübut — OUT ≠ ID qaytarma | ☐ | |
| S3 | 24s+ ID held overdue → Security bildirişi | ☐ | D07 |
| S4 | RETURN_PENDING izləmə (`?status=id_pending`) | ☐ | |

## C. Tickets

| # | Ssenari | Pass? | Qeyd |
|---|---------|-------|------|
| T1 | Rezident müraciət yaratma | ☐ | |
| T2 | Şöbə yönləndirmə / routing | ☐ | |
| T3 | Təyinat + status | ☐ | |
| T4 | WO (uyğun kateqoriya) + rezidentə görünən həll | ☐ | |

## D. Resident Portal

| # | Ssenari | Pass? | Qeyd |
|---|---------|-------|------|
| P1 | Login | ☐ | |
| P2 | Multi-company seçim / izolyasiya | ☐ | |
| P3 | Qonaq idarəetmə + cardless checkout | ☐ | |
| P4 | Ticketlər | ☐ | |
| P5 | Maliyyə sənəd paylaşımı / sübut yükləmə | ☐ | D05 |
| P6 | Bildirişlər | ☐ | |

## E. Paylaşılan asılılıqlar

| # | Xidmət | Status | Owner |
|---|--------|--------|-------|
| D1 | Şirkət / şəxs / sahə master data | Kod hazır | Ops |
| D2 | Membership + RBAC | Kod hazır | Dev / Ops |
| D3 | Audit | Kod hazır | — |
| D4 | Scheduled jobs (lease, guest overdue, AxTrax RO) | Lokal poller | Ops / NetAdmin |
| D5 | Private media | Kod hazır | NetAdmin (backup) |
| D6 | AxTrax oxu-only | Poller + LAN DoD | NetAdmin |

## F. Açıq qərarlar (sahib)

| Maddə | Owner | Status |
|-------|-------|--------|
| Real CoA + ƏDV xəritələmə | Finance | Açıq |
| LAN / TLS / AxTrax host | NetAdmin | Açıq |
| Backup / recovery hədəfləri | NetAdmin | Açıq |
| Sənəd retention müddətləri | Hüquq / Management | Açıq |
| Prod data seçimi və təmizlik | Management + City Point | **Ayrı qərar** — bu checklist-də icra olunmur |
| On-site operator imza (§C və s.) | Ops | Açıq |

**Operator imza:** ________________ · Tarix: ________
