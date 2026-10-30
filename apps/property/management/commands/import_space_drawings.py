"""Import per-office DXF/PNG from docs/City_Point_Ofisler_DXF_PNG using a mapping CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from apps.property.drawings import create_space_drawing
from apps.property.models import Space, SpaceDrawing, SpaceDrawingKind

DEFAULT_ROOT = Path(settings.BASE_DIR) / "docs" / "City_Point_Ofisler_DXF_PNG"


def load_mapping(path: Path) -> dict[str, str]:
    """CSV columns: package_id,space_code"""
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "package_id" not in reader.fieldnames or "space_code" not in reader.fieldnames:
            raise CommandError("Mapping CSV must have headers: package_id,space_code")
        for row in reader:
            pid = (row.get("package_id") or "").strip()
            code = (row.get("space_code") or "").strip()
            if pid and code:
                mapping[pid] = code
    return mapping


class Command(BaseCommand):
    help = (
        "Import SpaceDrawing from City_Point_Ofisler_DXF_PNG package. "
        "Requires mapping CSV (package_id,space_code). Unmapped packages are skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--root",
            default=str(DEFAULT_ROOT),
            help="Package root directory",
        )
        parser.add_argument(
            "--map",
            dest="map_path",
            default="",
            help="CSV path (default: <root>/space_drawing_map.csv)",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace existing drawings with same package_id+kind for the space",
        )

    def handle(self, *args, **options):
        root = Path(options["root"])
        if not root.is_dir():
            raise CommandError(f"Root not found: {root}")
        map_path = Path(options["map_path"]) if options["map_path"] else root / "space_drawing_map.csv"
        if not map_path.is_file():
            raise CommandError(
                f"Mapping CSV tapılmadı: {map_path}\n"
                "Yaradın: package_id,space_code (məs. F08_Ofis_01,CP-L048)"
            )
        mapping = load_mapping(map_path)
        dry = options["dry_run"]
        replace = options["replace"]

        stats = {"imported": 0, "skipped_no_map": 0, "skipped_no_space": 0, "skipped_missing_file": 0, "errors": 0}
        skipped: list[str] = []

        for json_path in sorted(root.rglob("*.json")):
            if json_path.name in {"office_register.json"} or "map" in json_path.name:
                continue
            try:
                meta = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.stderr.write(f"JSON oxunmadı {json_path}: {exc}")
                stats["errors"] += 1
                continue
            if not isinstance(meta, dict):
                continue
            package_id = (meta.get("id") or json_path.stem).strip()
            space_code = mapping.get(package_id)
            if not space_code:
                stats["skipped_no_map"] += 1
                skipped.append(package_id)
                continue
            space = Space.objects.filter(code=space_code).first()
            if not space:
                stats["skipped_no_space"] += 1
                skipped.append(f"{package_id}->{space_code} (space yox)")
                continue

            office_dir = json_path.parent
            pairs = []
            dxf_name = meta.get("dxf_file") or f"{package_id}.dxf"
            preview_name = meta.get("preview_file") or f"{package_id}.png"
            dxf_path = office_dir / dxf_name
            preview_path = office_dir / preview_name
            if dxf_path.is_file():
                pairs.append((SpaceDrawingKind.DXF, dxf_path))
            else:
                stats["skipped_missing_file"] += 1
            if preview_path.is_file():
                pairs.append((SpaceDrawingKind.TECHNICAL_PLAN, preview_path))
            # Also pick any .pdf in folder
            for pdf in office_dir.glob("*.pdf"):
                pairs.append((SpaceDrawingKind.TECHNICAL_PLAN, pdf))

            for kind, fpath in pairs:
                if dry:
                    self.stdout.write(f"DRY {package_id} -> {space_code} [{kind}] {fpath.name}")
                    stats["imported"] += 1
                    continue
                if replace:
                    SpaceDrawing.objects.filter(
                        space=space, kind=kind, package_id=package_id
                    ).delete()
                elif SpaceDrawing.objects.filter(space=space, kind=kind, package_id=package_id).exists():
                    self.stdout.write(f"skip existing {package_id} {kind}")
                    continue
                try:
                    with fpath.open("rb") as fh:
                        create_space_drawing(
                            space=space,
                            uploaded_file=File(fh, name=fpath.name),
                            kind=kind,
                            package_id=package_id,
                            build_svg=(kind == SpaceDrawingKind.DXF),
                        )
                    stats["imported"] += 1
                    self.stdout.write(self.style.SUCCESS(f"OK {package_id} -> {space_code} {fpath.name}"))
                except Exception as exc:  # noqa: BLE001
                    stats["errors"] += 1
                    self.stderr.write(f"ERR {package_id} {fpath.name}: {exc}")

        self.stdout.write(
            f"imported={stats['imported']} no_map={stats['skipped_no_map']} "
            f"no_space={stats['skipped_no_space']} missing_file={stats['skipped_missing_file']} "
            f"errors={stats['errors']}"
        )
        if skipped:
            self.stdout.write("Skipped (sample): " + ", ".join(skipped[:20]))
            if len(skipped) > 20:
                self.stdout.write(f"... +{len(skipped) - 20} more")
