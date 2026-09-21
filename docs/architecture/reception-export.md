## Export / reports (MVP)

- ERP: **Export CSV** on Reception (`/erp/reception/export/`) — Excel-compatible UTF-8 BOM CSV for today’s journal.
- Permission: `reception.export`; Seriya column uses full value only with `reception.view_sensitive_data`.
- Dashboard KPIs: Inside now | Today | Waiting/Pre-reg | ID return pending; API `/api/reception/today/` returns the same stats.
