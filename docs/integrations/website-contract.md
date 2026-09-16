# Website ↔ ERP Integration Contract (Stub)

**Status:** CONTRACT DRAFT — endpoints not live until Scope 4.  
**Rule:** Do not invent the real website backend schema. Align field names when website team provides OpenAPI.

## ERP → Website (public spaces)

**Purpose:** Publish vacant/marketable spaces only.

Suggested resource: `GET /api/v1/public/spaces`

Safe fields (whitelist):

- space code, floor, area_m2, description, amenities, photos, public availability flag  
**Never:** resident identity, lease terms, internal cost center, tickets, access zones internals.

## Website → ERP (leads)

Suggested resources:

- `POST /api/v1/public/leads` — inquiry  
- `POST /api/v1/public/viewings` — viewing request  

Minimum lead payload (draft):

```json
{
  "source": "website",
  "full_name": "...",
  "email": "...",
  "phone": "...",
  "company_name": "...",
  "message": "...",
  "interested_space_code": null,
  "external_id": "web-..."
}
```

**Requirements:** validation, rate limit, spam protection, duplicate detection (`email`+`phone`+time window), sync log, idempotency.

## Ownership

- Lead SoT after ingest: CRM (Scope 3)  
- Adapter: `apps.integrations.website`  
- Mapping: `ExternalIdentity` (system=`website`, external_id ↔ party/lead)

## Open questions (blocked)

1. Exact website CMS/API stack?
2. Auth method for public POST (honeypot, Turnstile CAPTCHA, shared secret)?
3. Photo CDN ownership?
