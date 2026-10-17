# Security floor plans (DWG/DXF → SVG + device pins)

## Overview

Security portal staff upload CAD floor plans, convert them to sanitized SVG on the server, activate a reviewed revision, and place device pins (cameras / signaling) on the plan.

## Building / Floor

- Each `SecurityFloorPlan` requires `floor` → `property.Floor`.
- Building is derived via `floor.building` (no redundant Building FK).

## Revisions

- Every upload creates a new `SecurityFloorPlanRevision` (source file kept forever).
- Only one revision per plan may be `is_active=True`.
- Pins belong to a **revision**; they are **not** auto-copied to a new revision.
- Activate only when `conversion_status=ready` and SVG exists (manual review).

## Formats

| Format | Conversion |
|--------|------------|
| **DXF** | Local `ezdxf` SVG backend → sanitize → store |
| **DWG** | Only if `SECURITY_DWG_CONVERTER` points to a local CLI that writes a DXF into an output directory. Otherwise status `unsupported`. |

Cloud / Autodesk Forge conversion is out of scope.

### Converter gate (NetAdmin)

1. Install a LAN-only DWG→DXF tool (e.g. ODA File Converter) offline.
2. Set `SECURITY_DWG_CONVERTER=/path/to/wrapper` (script: `wrapper <dwg> <outdir>` → writes `*.dxf`).
3. Rebuild/redeploy only after license and Docker compatibility are approved.
4. Until then, ask operators to export **DXF** from CAD.

Synthetic proof fixture: `apps/security/fixtures/sample_floor.dxf` (no sample DWG shipped).

## Worker

```bash
python manage.py convert_security_plans --once
# or poll:
python manage.py convert_security_plans --interval 30 --limit 5
```

- Claims pending rows with `SELECT … FOR UPDATE SKIP LOCKED` → `processing`.
- Failures: `failed` / `unsupported` with a short user-safe `conversion_error` (no stack traces / paths).
- Retry from the plan detail UI (Security/Admin).

Antivirus/sandbox before conversion: not wired; document if LAN AV is added later.

## Private storage

- Root: `PRIVATE_MEDIA_ROOT` (default `var/private_media`).
- Docker volume: `citypoint_private_media`.
- **Not** served under public `/media/`.
- Authenticated endpoints:
  - SVG: `GET /security/plans/<id>/revisions/<rid>/svg/` (`image/svg+xml`, `nosniff`, tight CSP) — use as `<img src>`.
  - Source: `GET …/download/` — `Content-Disposition: attachment`.

Backup/restore must include the private volume alongside the DB.

## SVG sanitization

Allowlisted elements only; blocks `script`, `foreignObject`, event handlers, `javascript:` / external URLs. SVG is never inlined into HTML templates.

## Permissions

| Role | View plans/devices/IP | Upload / activate / pins / devices |
|------|----------------------|-------------------------------------|
| Security | Yes | Yes |
| Admin | Yes | Yes |
| Management | Yes (view-only) | No |
| Reception / Resident / other staff | No | No |

Audit: `log_action(…, source="security_plans")` for upload, activate, retry, download, device and pin mutations.

## UI

- Nav: **Planlar**, **Cihazlar**.
- Viewer: pan/zoom; pins share the same transform; place pins in edit mode (Security/Admin).

## Settings

- `PRIVATE_MEDIA_ROOT`
- `SECURITY_PLAN_MAX_UPLOAD_MB` (default 40)
- `SECURITY_DWG_CONVERTER` (empty = DWG unsupported)
