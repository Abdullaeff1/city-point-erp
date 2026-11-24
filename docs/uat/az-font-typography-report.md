# City Point — Azərbaycan tipoqrafiyası (qəbul hesabatı)

**Tarix:** 24 Noyabr 2026  
**Seçilmiş şrift:** Noto Sans (SIL OFL) — yerli `static/fonts/noto-sans-{400,500,600,700}.woff2` + `OFL-NotoSans.txt`  
**Çəkilər:** 400 (adi), 500 (orta), 600 (yarımqalın), 700 (qalın)

## Tapılmış səbəb

Əvvəl UI **Manrope** / **Plus Jakarta Sans** latin-only `.woff2` alt dəstlərinə bağlanmışdı (`unicode-range` tam AZ əlifbasını əhatə etmirdi). `fontTools` cmap yoxlaması:

| Fayl | Əə Ğğ İı Öö Şş Üü Çç | ₼ |
|------|----------------------|---|
| `manrope-latin*.woff2` | yox | yox |
| `plus-jakarta-sans-latin*.woff2` | yox | yox |
| `noto-sans-400/700.woff2` | var | var |

Nəticə: «Rəhbərlik», «Əməkdaş» kimi sözlərdə latın hərfləri Manrope/Jakarta ilə, **Ə/ə** isə sistem ehtiyat şrifti ilə çəkilirdi — eyni sözdə fərqli qalınlıq/hündürlük.

**Müşahidə olunan ekranlar (əvvəl):** Rəhbərlik paneli (yan menyu, başlıq, KPI kartları), Rezident portalı (Əməkdaşlar, Şirkət), Mühasib/Maliyyə (Ödənişlər, Müqavilə). Brauzerdə yalnız `computed font-family` deyil, `document.fonts.check(..., ch)` ilə hər hərf üçün render şrifti yoxlanılıb.

## Düzəliş

1. Noto Sans 400–700 yerli woff2 + OFL lisenziyası.
2. `static/css/cp-theme.css`: `@font-face` + `--cp-font: "Noto Sans", …`; chrome elementləri `font-family: inherit`; `html[lang="az"]` üçün line-height / kəsilmənin qarşısı.
3. `cp-crm.css` / `cp.css`: latin-only `@font-face` silinib; `var(--cp-font)` istifadə olunur.
4. `templates/base.html`: `lang="{{ LANGUAGE_CODE }}"` — AZ rejimində `lang=az` (i→İ üçün `toLocaleUpperCase('az')` → **İCARƏ**).
5. Dar ekran: `overflow-wrap: anywhere` başlıqda hərfləri şaquli yığırdı (~390px). `cp-erp.css` + `cp-mgmt.css` mobil qaydası ilə düzəldildi; WhiteNoise `.css.gz` yeniləndi.

İkonlar Lucide SVG olaraq qalır — mətn şriftindən ayrı.

## Brauzerdə yoxlanmış nümunələr

| Portal | Nümunə sözlər | Rendered font (hər hərf) | Şrift URL |
|--------|---------------|--------------------------|-----------|
| Rəhbərlik `/erp/` | Rəhbərlik, Əmlak, İcarəyə hazır boş sahələr, Ödəniş | Noto Sans | yalnız `/static/fonts/noto-sans-*.woff2` |
| Mühasib `/finance/` | Maliyyə, Ödənişlər, Müqavilə, Şirkət, Əsas, Təchizatçı | Noto Sans | eyni, xarici sorğu yox |
| Rezident `/portal/` | Əməkdaşlar, Şirkət, İcarə, Əsas səhifə | Noto Sans | eyni |

**Dil keçidi:** AZ → EN → AZ: `html[lang]` düzgün dəyişir; Noto qalır; Google Fonts / gstatic yoxdur.  
**Böyük hərf:** `icarə` → az locale ilə **İCARƏ** (EN locale ilə `ICARƏ` olardı).

## Ekran görüntüləri

Eyni viewport müqayisəsi:

- Əvvəl (Manrope latin simulyasiyası): `docs/uat/screenshots/az-font-before-mgmt-1024.png`
- Sonra: `docs/uat/screenshots/az-font-after-mgmt-1024.png`
- Mobil 390: `docs/uat/screenshots/az-font-after-mgmt-390.png`
- Mühasib 1024: `docs/uat/screenshots/az-font-after-accountant-1024.png`
- Rezident 1024 / 390: `docs/uat/screenshots/az-font-after-resident-1024.png`, `…-resident-390.png`

## Hədəfli test

```text
manage.py test apps.core.tests.test_az_fonts
→ 2 OK, 1 skip (Docker-da brotli yoxdursa woff2 cmap skip; host-da glyph-lər təsdiqlənib)
```

Offline: bütün woff2 layihənin `static/fonts/` qovluğundadır; şəbəkə olmadan eyni görünüş.
