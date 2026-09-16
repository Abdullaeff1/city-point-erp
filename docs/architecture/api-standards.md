# API Standards (Scope 0 foundation)

## API surfaces (future)

| Surface | Auth | Consumers |
|---------|------|-----------|
| **Public** | API key / signed webhook + rate limit | City Point website |
| **Resident** | Session or token; company-scoped | Portal / future mobile |
| **Internal ERP** | Staff session / token + RBAC | Staff UI / internal tools |
| **Integration** | Service credentials + mTLS optional | Turnstile, email, accounting |

## Rules

1. Version prefix: `/api/v1/...`
2. JSON only; ISO-8601 datetimes; UTC stored, Asia/Baku displayed.
3. Idempotency-Key header on create for public/integration POSTs.
4. Errors: `{ "error": { "code": "...", "message": "...", "details": {} } }`
5. Pagination: `limit`/`offset` or cursor; default limit 50, max 200.
6. No business rules in serializers only — call domain services.
7. OpenAPI published when first public endpoint ships (Scope 4).

## Scope 0 delivery

- Standards documented (this file).
- Django REST Framework **not** required until Scope 3/4; stubs live under `apps.integrations`.
- Existing session UI unchanged.
