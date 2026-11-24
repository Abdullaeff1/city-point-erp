"""Azerbaijani UI fonts must be local and contain required glyphs."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class AzerbaijaniFontFilesTests(SimpleTestCase):
    NEEDED = {
        0x018F,  # Ə
        0x0259,  # ə
        0x011E,  # Ğ
        0x011F,  # ğ
        0x0130,  # İ
        0x0131,  # ı
        0x015E,  # Ş
        0x015F,  # ş
        0x00D6,  # Ö
        0x00F6,  # ö
        0x00DC,  # Ü
        0x00FC,  # ü
        0x00C7,  # Ç
        0x00E7,  # ç
        0x20BC,  # ₼
    }

    def _fonts_dir(self) -> Path:
        return Path(settings.BASE_DIR) / "static" / "fonts"

    def test_noto_sans_weights_present_with_license(self):
        root = self._fonts_dir()
        for name in (
            "noto-sans-400.woff2",
            "noto-sans-500.woff2",
            "noto-sans-600.woff2",
            "noto-sans-700.woff2",
        ):
            path = root / name
            self.assertTrue(path.is_file(), msg=name)
            self.assertGreater(path.stat().st_size, 50_000, msg=name)
        license_path = root / "OFL-NotoSans.txt"
        self.assertTrue(license_path.is_file())
        self.assertIn("SIL OPEN FONT LICENSE", license_path.read_text(encoding="utf-8"))

    def test_noto_sans_contains_azerbaijani_glyphs(self):
        try:
            from fontTools.ttLib import TTFont
        except ImportError:
            self.skipTest("fonttools not installed")

        root = self._fonts_dir()
        for name in ("noto-sans-400.woff2", "noto-sans-700.woff2"):
            try:
                font = TTFont(root / name)
            except ImportError as exc:
                self.skipTest(f"woff2 decode unavailable: {exc}")
            cps: set[int] = set()
            for table in font["cmap"].tables:
                cps.update(table.cmap.keys())
            missing = sorted(self.NEEDED - cps)
            self.assertEqual(missing, [], msg=f"{name} missing {[hex(c) for c in missing]}")

    def test_theme_css_references_noto_not_latin_only_manrope(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "cp-theme.css").read_text(
            encoding="utf-8"
        )
        self.assertIn('font-family: "Noto Sans"', css)
        self.assertIn("noto-sans-400.woff2", css)
        self.assertIn("noto-sans-700.woff2", css)
        self.assertNotIn("manrope-latin.woff2", css)
        crm = (Path(settings.BASE_DIR) / "static" / "css" / "cp-crm.css").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("plus-jakarta-sans-latin.woff2", crm)
        self.assertIn("var(--cp-font", crm)
