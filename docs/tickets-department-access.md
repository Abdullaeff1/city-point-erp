# Ticket şöbə görünürlüyü və idarəetmə

## Audit xülasəsi (Faza 0)

**Qorunur:** `Ticket`, `TicketDepartment`, `TicketQueue`, `RoutingRule`, `TicketStatusEvent`,
`TicketRoutingEvent`, SLA, `can_transition_to()`, portal create + `route_ticket()`, rezident company scoping.

**Dəyişir:** ERP/Security/dashboard ticket queryset-ləri; status/assignee/handoff/WO/CRM xidmət
qatında icazə; attachment download ACL; Security `department__code=security` hardcode silinir;
şöbə bildirişləri (`event_key` dedup).

**Rol ≠ şöbə:** `SERVICE_DESK` / `PROPERTY_FM` / `SECURITY` avtomatik `TicketDepartment` demək
deyil. Admin istifadəçiyə `ticket_department` əl ilə təyin edir. Migration avtomatik map etmir.

## `User.ticket_department` FK

Nullable FK → `tickets.TicketDepartment`. Migration yalnız sütun əlavə edir; heç kimi avtomatik
map etmir.

## Avtomatik şöbə yönləndirmə

Portal / kart sifarişi ticket yaradılarkən `create_ticket_from_portal` → `route_ticket()`
alt kateqoriyanın `RoutingRule`-una görə **avtomatik** `department` + `queue` təyin edir.
Status, assignee, prioritet və digər mutasiyaları yalnız həmin şöbənin staff-ı (və ya
Admin/Management) edə bilər — `can_mutate_ticket`.

## Əməkdaşa ticket şöbəsi təyin etmək

1. Django Admin → İstifadəçi → **Ticket department** sahəsini seçin.
2. Nümunə: Security → `security`, Service Desk → `servicedesk`, FM → `property` / `webservis` / `teserrufat`.
3. Şöbəsiz staff ticket siyahısını boş görür və dəyişiklik edə bilməz.
4. Admin / Management üçün FK boş ola bilər — onlar bütün ticketləri görür.
5. Demo seed: `desk`→servicedesk, `fm`→webservis, `security`→security.

## ADMIN / MANAGEMENT

`ticket_department` boş qala bilər. Bütün ticketləri görür və idarə edir; şöbələrarası handoff
yalnız onlar üçündür.

## Access helper-lər (`apps/tickets/access.py`)

| Funksiya | Davranış |
|----------|----------|
| `can_view_all_tickets` | Admin / Management |
| `tickets_visible_to` | all / dept FK / `.none()` |
| `can_view_ticket` | staff şöbə görünüşü |
| `can_mutate_ticket` | staff mutate; rezident həmişə `False` |
| `can_access_ticket_attachment` | staff: `can_view_ticket`; rezident: eyni şirkət |
| `can_handoff_ticket` | yalnız Admin / Management |

## Attachment

Protected URL: `ticket_attachment_download` (ERP + Security + Portal).

- Staff — yalnız öz şöbəsinin ticket faylı
- Rezident — yalnız öz şirkətinin ticket faylı
- Birbaşa `/media/tickets/...` linkləri template-lərdə istifadə olunmur

## Service-layer icazə

Status, assignee, priority, enrich, attach, handoff, WO, CRM — `apps/tickets/services.py`
içində `actor` + `can_mutate_ticket` / `can_handoff_ticket` yoxlanır. View bypass keçmir;
xətalar mövcud `DomainError` ilə qayıdır (yeni exception tipi yoxdur).

- `set_ticket_status` / `advance_ticket_status`: mutate + `can_transition_to`; WAITING səbəbi məcburi
- `assign_ticket`: assignee eyni `ticket_department`
- `handoff_ticket`: yalnız Admin/Management; `TicketRoutingEvent` yazılır

## Bildirişlər

`notify_company_users` + `notify_department_users` — `transaction.on_commit`; xəta ticket-i
geri çevirmir.

**Dedup:** sabit `event_key` (məs. `ticket.status.{id}.{status_event_id}`). Eyni `(user, event_key)`
təkrar insert olunmur. Eyni mətnli iki ayrı hadisə fərqli `event_key` → hər ikisi göndərilir.

## Yeni TicketDepartment

Taxonomy seed və ya Admin vasitəsilə `TicketDepartment` + `TicketQueue` + `RoutingRule` əlavə edin.
İcazə qaydaları hardcoded şöbə koduna bağlı deyil — yalnız `User.ticket_department` FK.

## Scope xaricində

Reception ticket UI; warehouse yeni dept; OrgDepartment birləşməsi; export/API; staff queue redaktoru.
