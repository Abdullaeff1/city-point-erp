# Security plan fixtures

- `sample_floor.dxf` — synthetic DXF (rectangle + text) for ezdxf → SVG proof.
- No sample DWG is shipped; DWG conversion stays **unsupported** until NetAdmin installs a local converter (`SECURITY_DWG_CONVERTER`).

Regenerate DXF:

```bash
python manage.py shell -c "from apps.security.fixtures.build_sample_dxf import main; main()"
```
