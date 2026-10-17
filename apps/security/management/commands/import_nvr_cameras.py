"""Import cameras/NVRs from docs/NVR_ve_Kameralar.xlsx into SecurityDevice."""

from __future__ import annotations

import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from apps.audit.services import log_action
from apps.security.models import DeviceType, SecurityDevice

IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
FLOOR_RE = re.compile(
    r"^(F-1|F1[0-3]?|F[2-9]|Parking|Perimetr|Plaza|Bank|OUT|PTZ)",
    re.I,
)


def _floor_from_name(name: str) -> str:
    m = FLOOR_RE.match(name.strip())
    if not m:
        return ""
    raw = m.group(1)
    up = raw.upper()
    if up in {"F-1", "F-1"}:
        return "F-1"
    if up.startswith("F") and up[1:].isdigit():
        return f"F{int(up[1:])}"
    return raw


class Command(BaseCommand):
    help = "Import NVR/camera rows from Excel into SecurityDevice (idempotent by IP)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="docs/NVR_ve_Kameralar.xlsx",
            help="Path to workbook (default: docs/NVR_ve_Kameralar.xlsx)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report without writing",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")

        wb = load_workbook(path, data_only=True)
        sheet = wb[wb.sheetnames[0]]
        nvr = ""
        cameras: list[dict] = []
        nvr_ips: set[str] = set()

        for r in range(1, sheet.max_row + 1):
            b = sheet.cell(r, 2).value
            c = sheet.cell(r, 3).value
            d = sheet.cell(r, 4).value
            if isinstance(b, str) and b.strip().upper().startswith("NVR"):
                nvr = b.strip()
                m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", nvr)
                if m:
                    nvr_ips.add(m.group(1))
                continue
            if b == "Channel" or c == "Camera Name":
                continue
            ip = str(d).strip() if d is not None else ""
            if not c or not IP_RE.match(ip):
                continue
            name = str(c).strip()
            cameras.append(
                {
                    "name": name,
                    "ip": ip,
                    "nvr": nvr,
                    "channel": b,
                    "port": sheet.cell(r, 5).value,
                    "floor": _floor_from_name(name),
                }
            )

        self.stdout.write(f"Parsed cameras={len(cameras)} nvrs={len(nvr_ips)}")
        if options["dry_run"]:
            return

        created = updated = 0
        with transaction.atomic():
            for ip in sorted(nvr_ips):
                note = f"NVR · {ip}"
                obj, was_created = SecurityDevice.objects.update_or_create(
                    ip_address=ip,
                    defaults={
                        "name": f"NVR {ip}",
                        "device_type": DeviceType.OTHER,
                        "location_note": note,
                        "is_active": True,
                    },
                )
                # Prefer unique name match if IP collision with camera (shouldn't)
                if was_created:
                    created += 1
                else:
                    updated += 1
                log_action(
                    action="security_device.import_nvr",
                    entity=obj,
                    new_values={"ip": ip},
                    source="security_plans",
                )

            for cam in cameras:
                # Skip if this IP is an NVR host
                if cam["ip"] in nvr_ips:
                    continue
                parts = [p for p in [cam["floor"], cam["nvr"], f"ch {cam['channel']}"] if p]
                note = " · ".join(str(p) for p in parts)
                obj, was_created = SecurityDevice.objects.update_or_create(
                    ip_address=cam["ip"],
                    defaults={
                        "name": cam["name"][:160],
                        "device_type": DeviceType.CAMERA,
                        "location_note": note[:255],
                        "is_active": True,
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. created={created} updated={updated} "
                f"total_devices={SecurityDevice.objects.count()}"
            )
        )
