#!/usr/bin/env python3
"""City Point AlmaLinux 10 NetAdmin — tam quraşdırma rəhbəri (Word). Bütün şəbəkə variantları."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "deployment"
    / "CityPoint_AlmaLinux10_NetAdmin_Tam_Rehberi.docx"
)

# Also refresh legacy filename for existing links
OUT_LEGACY = OUT.parent / "CityPoint_AlmaLinux10_Native_Offline_Rehberi.docx"


def set_run_font(run, size=11, bold=False, color=None):
    run.font.name = "Calibri"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = color


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        set_run_font(
            run,
            size=16 if level == 1 else 13 if level == 2 else 12,
            bold=True,
            color=RGBColor(0x1F, 0x49, 0x7D),
        )
    return h


def add_para(doc, text, *, bold=False, size=11, space_after=8, align=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    if align:
        p.alignment = align
    run = p.add_run(text)
    set_run_font(run, size=size, bold=bold)
    return p


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(style="List Bullet")
    p.clear()
    if level:
        p.paragraph_format.left_indent = Cm(0.75 * level)
    run = p.add_run(text)
    set_run_font(run)
    return p


def add_code(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.left_indent = Cm(0.5)
    run = p.add_run(text)
    run.font.name = "Consolas"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    run.font.size = Pt(8)
    return p


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        run = hdr[i].paragraphs[0].add_run(h)
        set_run_font(run, bold=True, size=9)
    for r_i, row in enumerate(rows):
        cells = table.rows[r_i + 1].cells
        for c_i, val in enumerate(row):
            cells[c_i].text = ""
            run = cells[c_i].paragraphs[0].add_run(str(val))
            set_run_font(run, size=9)
    doc.add_paragraph()
    return table


def add_link_para(doc, label, url):
    p = doc.add_paragraph()
    run = p.add_run(f"{label}: ")
    set_run_font(run)
    run = p.add_run(url)
    set_run_font(run, size=10)
    run.font.color.rgb = RGBColor(0x05, 0x63, 0xC1)
    run.underline = True
    return p


def build():
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("CITY POINT ERP / PORTAL / SECURITY")
    set_run_font(r, size=22, bold=True, color=RGBColor(0x1F, 0x49, 0x7D))

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("AlmaLinux 10 — NetAdmin tam quraşdırma rəhbəri (Docker yox · bütün şəbəkə variantları)")
    set_run_font(r, size=13, bold=True)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = meta.add_run(
        f"Versiya: 3.0  ·  Tarix: {date.today().isoformat()}  ·  "
        "Auditoriya: NetAdmin / SysAdmin / ERP ops  ·  ÖZÜNÜ-KİFAYƏT"
    )
    set_run_font(r, size=9, color=RGBColor(0x64, 0x74, 0x8B))

    add_para(
        doc,
        "Bu sənəd ÖZÜNÜ-KİFAYƏTDİR. AlmaLinux 10-da sistemi qaldırmaq üçün lazım olan bütün "
        "əmrlər, SQL, Nginx, systemd, .env, firewall, backup, AxTrax və go-live yoxlamaları "
        "buradadır. Başqa markdown/GitHub səhifəsinə baxmağa ehtiyac yoxdur — yalnız USB-dən "
        "gələn citypoint-app.zip (Django mənbə kodu) + wheelhouse + offline RPM qovluqları lazımdır. "
        "NetAdmin variant seçib (A/B/C × I/II/III) aşağıdakı hazır kod bloklarını bir-bir kopyalayıb "
        "serverə yapışdırır.",
        bold=True,
    )
    add_bullet(doc, "USB məzmunu: citypoint-app.zip + wheelhouse/ + rpms/ (bu sənədin §9–§10)")
    add_bullet(doc, "Bütün konfiq fayllarının TAM mətni §13 və §22 (Əlavə) bölmələrindədir")
    add_bullet(doc, "Docker bu rəhbərdə YOXDUR — native PostgreSQL + Gunicorn + Nginx + systemd")

    # ========== SEÇİM VƏRƏQİ ==========
    add_heading(doc, "Seçim vərəqi (NetAdmin doldurur)", 1)
    add_table(
        doc,
        ["Sual", "Seçiminiz (A/B/C və ya I/II/III)", "Qeyd"],
        [
            ["Rezident Portal girişi", "A / B / C", "A=public HTTPS; B=VPN+daxili URL; C=faza1 staff"],
            ["Server İnternet uplink", "I / II / III", "I=air-gap; II=məhdud inbound; III=outbound patch"],
            ["Server statik IP (daxili)", "", "məs. 10.20.30.40"],
            ["Server hostname", "", "məs. erp.citypoint.local"],
            ["Public portal FQDN (A)", "", "məs. portal.citypoint.az"],
            ["Office LAN subnet", "", "məs. 10.20.0.0/24"],
            ["AxTrax SQL host:port/DB", "", "məs. 172.31.104.10:1433 / AxTrax1"],
            ["AxTrax RO istifadəçi", "", "ReadOnlyerp"],
        ],
    )
    add_para(doc, "Kombinasiya bələdçisi:", bold=True)
    add_bullet(doc, "A + II və ya A + III: public Portal (443) + staff daxili ERP — ən tipik xarici rezident ssenarisi")
    add_bullet(doc, "B + I: tam air-gap + VPN — rezidentlər VPN ilə daxil olur")
    add_bullet(doc, "C + I: əvvəl yalnız reception/security; rezident Portal sonra")
    add_bullet(doc, "A + I: public HTTPS air-gap serverdə çətindir — TLS cert USB/import və ya ayrı edge proxy lazımdır")

    # ========== 1 VERSİYALAR ==========
    add_heading(doc, "1. Proqram versiyaları (mütləq uyğunluq)", 1)
    add_table(
        doc,
        ["Komponent", "Versiya", "Mənbə / yoxlama"],
        [
            ["OS", "AlmaLinux 10 x86_64", "cat /etc/almalinux-release"],
            ["Python", "3.12.x", "python3.12 --version"],
            ["Django", "5.1 – 5.2.x", "requirements.txt layihədə"],
            ["PostgreSQL", "16.x", "psql --version"],
            ["Gunicorn", "≥ 23", "pip show gunicorn"],
            ["psycopg", "≥ 3.2 (binary)", "pip show psycopg"],
            ["pymssql", "≥ 2.3", "pip show pymssql + freetds"],
            ["Whitenoise", "≥ 6.8", "statik CDN yoxdur"],
        ],
    )

    add_heading(doc, "1.1 Haradan yükləmək (linklər)", 2)
    add_link_para(doc, "AlmaLinux 10 ISO", "https://repo.almalinux.org/almalinux/10/isos/x86_64/")
    add_link_para(doc, "AlmaLinux 10 BaseOS repo (build maşını)", "https://repo.almalinux.org/almalinux/10/BaseOS/x86_64/os/")
    add_link_para(doc, "AlmaLinux 10 AppStream", "https://repo.almalinux.org/almalinux/10/AppStream/x86_64/os/")
    add_link_para(doc, "PostgreSQL PGDG (alternativ, build maşını)", "https://www.postgresql.org/download/linux/redhat/")
    add_link_para(doc, "Python 3.12 (rəsmi)", "https://www.python.org/downloads/")
    add_para(doc, "Air-gap prod server ISO və RPM-ləri USB ilə gətirir; aşağıdakı dnf/pip əmrləri build maşınındadır.")

    # ========== 2 ARXİTEKTURA ==========
    add_heading(doc, "2. Arxitektura", 1)
    add_code(
        doc,
        "                    City Point binası (LAN)\n"
        "  ┌──────────────────────────────────────────────────────┐\n"
        "  │ Staff PC (reception, security, FM) ──► ERP (daxili)   │\n"
        "  │ AlmaLinux 10 server                                   │\n"
        "  │   ├─ PostgreSQL 16 (127.0.0.1:5432)                   │\n"
        "  │   ├─ Gunicorn + Django (127.0.0.1:8000)               │\n"
        "  │   ├─ systemd: citypoint-web, citypoint-axtrax        │\n"
        "  │   └─ Nginx (:80/:443) — variantdan asılı             │\n"
        "  │            │                                          │\n"
        "  │            └──► AxTrax MS SQL (LAN, RO, :1433)        │\n"
        "  └──────────────────────────────────────────────────────┘\n"
        "  Rezident ofisi (LAN xaricində):\n"
        "    Variant A: İnternet ──HTTPS──► portal FQDN (yalnız /portal/)\n"
        "    Variant B: VPN ──► daxili URL (portal.citypoint.local)\n"
        "    Variant C: hələ yox (faza 2)",
    )

    add_heading(doc, "2.1 Server resursları", 2)
    add_table(
        doc,
        ["Resurs", "Minimum", "Tövsiyə"],
        [
            ["CPU", "4 vCPU", "8 vCPU"],
            ["RAM", "8 GB", "16 GB"],
            ["Disk", "100 GB SSD", "200+ GB (DB+media+/backup)"],
            ["Şəbəkə", "1 Gbit, statik IP", "Dual NIC (LAN + DMZ) — variant A üçün"],
        ],
    )

    # ========== 3 REZİDENT VARIANTLARI ==========
    add_heading(doc, "3. Rezident Portal — variant A (public HTTPS)", 1)
    add_para(doc, "Rezidentlər binadan kənarda; Portal public domain ilə açılır. ERP/Admin public İnternetə verilmir.")
    add_table(
        doc,
        ["Parametr", "Nə yazılmalıdır"],
        [
            ["Public DNS", "portal.citypoint.az → public IP (NAT/firewall)"],
            ["Daxili ERP DNS", "erp.citypoint.local → daxili IP (yalnız office LAN/VPN)"],
            ["DJANGO_ALLOWED_HOSTS", "portal.citypoint.az,erp.citypoint.local,<daxili-ip>"],
            ["DJANGO_CSRF_TRUSTED_ORIGINS", "https://portal.citypoint.az,https://erp.citypoint.local"],
            ["SESSION_COOKIE_SECURE", "1"],
            ["CSRF_COOKIE_SECURE", "1"],
            ["SECURE_SSL_REDIRECT", "1 (portal vhost)"],
            ["invite --base-url", "https://portal.citypoint.az"],
        ],
    )
    add_para(doc, "Nginx — portal (public), yalnız portal yolları:", bold=True)
    add_code(
        doc,
        "# /etc/nginx/conf.d/citypoint-portal-public.conf\n"
        "server {\n"
        "    listen 443 ssl http2;\n"
        "    server_name portal.citypoint.az;\n"
        "    ssl_certificate     /etc/pki/tls/certs/portal.citypoint.az.crt;\n"
        "    ssl_certificate_key /etc/pki/tls/private/portal.citypoint.az.key;\n"
        "    client_max_body_size 50M;\n"
        "\n"
        "    location /static/ { alias /opt/citypoint/staticfiles/; }\n"
        "    location /media/  { alias /opt/citypoint/media/; }\n"
        "\n"
        "    location /erp/     { return 404; }\n"
        "    location /admin/   { return 404; }\n"
        "    location /security/ { return 404; }\n"
        "\n"
        "    location / {\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "    }\n"
        "}\n"
        "server {\n"
        "    listen 80;\n"
        "    server_name portal.citypoint.az;\n"
        "    return 301 https://$host$request_uri;\n"
        "}",
    )
    add_para(doc, "Nginx — ERP (yalnız daxili şəbəkə):", bold=True)
    add_code(
        doc,
        "# /etc/nginx/conf.d/citypoint-erp-internal.conf\n"
        "server {\n"
        "    listen 443 ssl;\n"
        "    server_name erp.citypoint.local;\n"
        "    ssl_certificate     /etc/pki/tls/certs/erp.citypoint.local.crt;\n"
        "    ssl_certificate_key /etc/pki/tls/private/erp.citypoint.local.key;\n"
        "    client_max_body_size 50M;\n"
        "    location /static/ { alias /opt/citypoint/staticfiles/; }\n"
        "    location /media/  { alias /opt/citypoint/media/; }\n"
        "    location / {\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "    }\n"
        "}",
    )
    add_para(doc, "firewalld (nümunə — office subnet 10.20.0.0/24):", bold=True)
    add_code(
        doc,
        "sudo firewall-cmd --permanent --new-zone=citypoint_public\n"
        "sudo firewall-cmd --permanent --zone=citypoint_public --add-service=https\n"
        "sudo firewall-cmd --permanent --zone=citypoint_public --add-service=http\n"
        "sudo firewall-cmd --permanent --zone=public --remove-service=https\n"
        "sudo firewall-cmd --permanent --zone=public --remove-service=http\n"
        "sudo firewall-cmd --permanent --zone=internal --add-source=10.20.0.0/24\n"
        "sudo firewall-cmd --permanent --zone=internal --add-service=https\n"
        "sudo firewall-cmd --reload",
    )
    add_para(doc, "Login rate limit (Nginx):", bold=True)
    add_code(
        doc,
        "limit_req_zone $binary_remote_addr zone=cp_login:10m rate=5r/m;\n"
        "location /login/ {\n"
        "    limit_req zone=cp_login burst=10 nodelay;\n"
        "    proxy_pass http://127.0.0.1:8000;\n"
        "}",
    )

    add_heading(doc, "4. Rezident Portal — variant B (VPN + daxili URL)", 1)
    add_table(
        doc,
        ["Parametr", "Nə yazılmalıdır"],
        [
            ["VPN", "WireGuard/OpenVPN/RRAS — rezident subnet VPN pool-a düşür"],
            ["Portal URL", "http(s)://portal.citypoint.local"],
            ["ALLOWED_HOSTS", "portal.citypoint.local,erp.citypoint.local,<server-ip>"],
            ["CSRF (HTTP)", "http://portal.citypoint.local,http://erp.citypoint.local"],
            ["CSRF (HTTPS daxili CA)", "https://portal.citypoint.local,https://erp.citypoint.local"],
            ["CP_OFFLINE", "1 (SMTP yoxdursa); invite link admin təhvil verir"],
            ["Firewall IN", "443/80 yalnız 10.20.0.0/24 + VPN subnet; public blok"],
        ],
    )
    add_code(
        doc,
        "# /etc/nginx/conf.d/citypoint-internal.conf\n"
        "server {\n"
        "    listen 80;\n"
        "    server_name portal.citypoint.local erp.citypoint.local;\n"
        "    client_max_body_size 50M;\n"
        "    location /static/ { alias /opt/citypoint/staticfiles/; }\n"
        "    location /media/  { alias /opt/citypoint/media/; }\n"
        "    location / {\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "    }\n"
        "}",
    )

    add_heading(doc, "5. Rezident Portal — variant C (faza 1: yalnız staff)", 1)
    add_bullet(doc, "Go-live: reception, security, admin, ticket, qonaq, AxTrax")
    add_bullet(doc, ".env: ALLOWED_HOSTS=erp.citypoint.local,<ip>; CSRF yalnız ERP host")
    add_bullet(doc, "Firewall: yalnız office LAN → 80/443")
    add_bullet(doc, "Faza 2: variant A və ya B qaydalarını əlavə et + invite_portal_user")

    # ========== INTERNET VARIANTLARI ==========
    add_heading(doc, "6. Server İnternet — variant I (tam air-gap)", 1)
    add_bullet(doc, "Prod serverdə İnternet yox; bütün RPM/wheel/kod USB ilə")
    add_bullet(doc, "Build maşını: AlmaLinux 10, İnternet VAR (aşağıdakı §8)")
    add_bullet(doc, "Public HTTPS (variant A) üçün: sertifikatı build maşınında alıb USB ilə import VƏ ya ayrı edge proxy")

    add_heading(doc, "7. Server İnternet — variant II (məhdud inbound 443)", 1)
    add_bullet(doc, "Outbound: default deny; daxili DNS; daxili SMTP 25/587 icazəli")
    add_bullet(doc, "Inbound: 443 public (portal); ERP yalnız internal zone")
    add_bullet(doc, "Let's Encrypt mümkün (ACME outbound 443) — certbot nümunəsi §15")
    add_bullet(doc, "App yeniləməsi yenə wheelhouse (runtime pip pull tövsiyə olunmur)")

    add_heading(doc, "8. Server İnternet — variant III (outbound patch/TLS)", 1)
    add_bullet(doc, "dnf upgrade daxili mirror və ya məhdud outbound")
    add_bullet(doc, "Go-live günü: pip --no-index (deterministik)")
    add_bullet(doc, "Docker Hub / runtime PyPI asılılığı yoxdur")

    # ========== BUILD MAŞINI ==========
    add_heading(doc, "9. Build maşını — paket hazırlığı (tam əmrlər)", 1)
    add_heading(doc, "9.1 OS və alətlər", 2)
    add_code(
        doc,
        "sudo dnf -y update\n"
        "sudo dnf -y install dnf-plugins-core createrepo_c git zip unzip tar gzip\n"
        "sudo dnf -y install python3.12 python3.12-pip python3.12-devel || \\\n"
        "  sudo dnf -y install python3 python3-pip python3-devel\n"
        "python3 --version",
    )
    add_heading(doc, "9.2 Tətbiq arxivi", 2)
    add_code(
        doc,
        "git clone <REPO_URL> city-point-system\n"
        "cd city-point-system\n"
        "git archive --format=zip --output=/media/usb/citypoint-app.zip HEAD\n"
        "# və ya: zip -r /media/usb/citypoint-app.zip . -x '*.git*' -x '*__pycache__*' -x 'media/*'",
    )
    add_heading(doc, "9.3 Python wheelhouse (offline pip)", 2)
    add_code(
        doc,
        "cd city-point-system\n"
        "python3 -m venv /tmp/cp-wh-build\n"
        "source /tmp/cp-wh-build/bin/activate\n"
        "pip install --upgrade pip wheel\n"
        "mkdir -p /media/usb/wheelhouse\n"
        "pip download -r requirements.txt -d /media/usb/wheelhouse\n"
        "pip download pip setuptools wheel -d /media/usb/wheelhouse\n"
        "ls -la /media/usb/wheelhouse | wc -l",
    )
    add_para(doc, "Wheelhouse AlmaLinux 10 x86_64 + eyni Python versiyası ilə hazırlanmalıdır.", bold=True)

    add_heading(doc, "9.4 Offline RPM repozitoriyası", 2)
    add_code(
        doc,
        "sudo dnf -y install 'dnf-command(download)'\n"
        "mkdir -p /media/usb/rpms && cd /media/usb/rpms\n"
        "sudo dnf download --resolve --alldeps --arch=x86_64 \\\n"
        "  python3 python3-pip python3-devel \\\n"
        "  postgresql-server postgresql postgresql-contrib \\\n"
        "  nginx firewalld chrony \\\n"
        "  freetds freetds-libs openssl-libs libpq \\\n"
        "  unzip tar gzip policycoreutils-python-utils\n"
        "# PG 16 AppStream adı: dnf search postgresql\n"
        "createrepo_c .\n"
        "du -sh .",
    )

    # ========== PROD OS ==========
    add_heading(doc, "10. Prod server — AlmaLinux 10 quraşdırma", 1)
    add_code(
        doc,
        "# ISO ilə quraşdırma (Minimal və ya Server)\n"
        "# Hostname: erp.citypoint.local\n"
        "# Statik IP: 10.20.30.40/24 (nümunə)\n"
        "# Timezone: Asia/Baku\n"
        "sudo timedatectl set-timezone Asia/Baku\n"
        "sudo hostnamectl set-hostname erp.citypoint.local",
    )
    add_heading(doc, "10.1 Offline RPM quraşdırma", 2)
    add_code(
        doc,
        "sudo mkdir -p /opt/offline/rpms\n"
        "sudo cp -a /mnt/usb/rpms/. /opt/offline/rpms/\n"
        "sudo tee /etc/yum.repos.d/citypoint-offline.repo <<'EOF'\n"
        "[citypoint-offline]\n"
        "name=CityPoint Offline RPMs\n"
        "baseurl=file:///opt/offline/rpms\n"
        "enabled=1\n"
        "gpgcheck=0\n"
        "EOF\n"
        "sudo dnf clean all\n"
        "sudo dnf --disablerepo='*' --enablerepo=citypoint-offline install -y \\\n"
        "  python3 python3-pip python3-devel \\\n"
        "  postgresql-server postgresql postgresql-contrib \\\n"
        "  nginx firewalld chrony freetds freetds-libs \\\n"
        "  unzip tar gzip",
    )
    add_heading(doc, "10.2 chrony və firewalld", 2)
    add_code(
        doc,
        "sudo systemctl enable --now chronyd\n"
        "sudo systemctl enable --now firewalld\n"
        "# Variant C / B: office LAN\n"
        "sudo firewall-cmd --permanent --zone=internal --add-source=10.20.0.0/24\n"
        "sudo firewall-cmd --permanent --zone=internal --add-service=http\n"
        "sudo firewall-cmd --permanent --zone=internal --add-service=https\n"
        "# AxTrax çıxış (host → MS SQL)\n"
        "sudo firewall-cmd --permanent --direct --add-rule ipv4 filter OUTPUT 0 -p tcp --dport 1433 -j ACCEPT\n"
        "sudo firewall-cmd --reload\n"
        "# 5432 heç vaxt xaricə açılmamalıdır",
    )

    # ========== POSTGRES ==========
    add_heading(doc, "11. PostgreSQL 16 (native)", 1)
    add_code(
        doc,
        "sudo postgresql-setup --initdb\n"
        "sudo systemctl enable --now postgresql\n"
        "sudo -u postgres psql <<'SQL'\n"
        "CREATE DATABASE citypoint;\n"
        "CREATE ROLE cp_migrator LOGIN PASSWORD 'CHANGE_ME_MIGRATOR';\n"
        "CREATE ROLE cp_app LOGIN PASSWORD 'CHANGE_ME_APP';\n"
        "CREATE ROLE cp_readonly LOGIN PASSWORD 'CHANGE_ME_READONLY';\n"
        "GRANT CONNECT ON DATABASE citypoint TO cp_migrator, cp_app, cp_readonly;\n"
        "\\c citypoint\n"
        "GRANT USAGE ON SCHEMA public TO cp_migrator, cp_app, cp_readonly;\n"
        "GRANT ALL ON SCHEMA public TO cp_migrator;\n"
        "SQL",
    )
    add_para(doc, "postgresql.conf (sudo vi /var/lib/pgsql/data/postgresql.conf):", bold=True)
    add_code(doc, "listen_addresses = 'localhost'")
    add_para(doc, "pg_hba.conf — yalnız local:", bold=True)
    add_code(
        doc,
        "# TYPE  DATABASE    USER        ADDRESS         METHOD\n"
        "local   all         postgres                    peer\n"
        "host    citypoint   cp_app      127.0.0.1/32    scram-sha-256\n"
        "host    citypoint   cp_migrator 127.0.0.1/32    scram-sha-256\n"
        "host    citypoint   cp_readonly 127.0.0.1/32    scram-sha-256",
    )
    add_para(doc, "Migrate-dən SONRA (cp_migrator ilə migrate edildikdən sonra):", bold=True)
    add_code(
        doc,
        "sudo -u postgres psql -d citypoint <<'SQL'\n"
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cp_app;\n"
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cp_app;\n"
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO cp_readonly;\n"
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cp_readonly;\n"
        "ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public\n"
        "  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cp_app;\n"
        "ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public\n"
        "  GRANT USAGE, SELECT ON SEQUENCES TO cp_app;\n"
        "ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public\n"
        "  GRANT SELECT ON TABLES TO cp_readonly;\n"
        "SQL",
    )

    # ========== APP ==========
    add_heading(doc, "12. Tətbiq quraşdırması", 1)
    add_code(
        doc,
        "sudo mkdir -p /opt/citypoint /opt/offline/wheelhouse /backup/citypoint\n"
        "sudo useradd -r -m -d /opt/citypoint -s /bin/bash citypoint 2>/dev/null || true\n"
        "sudo unzip -o /mnt/usb/citypoint-app.zip -d /opt/citypoint\n"
        "sudo cp -a /mnt/usb/wheelhouse/. /opt/offline/wheelhouse/\n"
        "sudo chown -R citypoint:citypoint /opt/citypoint /backup/citypoint\n"
        "\n"
        "sudo -u citypoint -H bash <<'EOF'\n"
        "cd /opt/citypoint\n"
        "python3 -m venv .venv\n"
        "source .venv/bin/activate\n"
        "pip install --no-index --find-links=/opt/offline/wheelhouse -r requirements.txt\n"
        "mkdir -p media staticfiles var/mail_outbox var\n"
        "EOF",
    )

    add_heading(doc, "12.1 .env — tam şablon (native prod)", 2)
    add_code(
        doc,
        "sudo -u citypoint tee /opt/citypoint/bin/prod/.env <<'EOF'\n"
        "CP_ENV=production\n"
        "CP_OFFLINE=1\n"
        "DJANGO_SECRET_KEY=REPLACE_WITH_STRONG_RANDOM\n"
        "DJANGO_DEBUG=0\n"
        "SEED_DEMO=0\n"
        "\n"
        "# Variant A/B/C üzrə düzəldin:\n"
        "DJANGO_ALLOWED_HOSTS=portal.citypoint.az,erp.citypoint.local,10.20.30.40\n"
        "DJANGO_CSRF_TRUSTED_ORIGINS=https://portal.citypoint.az,https://erp.citypoint.local\n"
        "\n"
        "POSTGRES_DB=citypoint\n"
        "POSTGRES_USER=cp_app\n"
        "POSTGRES_PASSWORD=CHANGE_ME_APP\n"
        "POSTGRES_HOST=127.0.0.1\n"
        "POSTGRES_PORT=5432\n"
        "\n"
        "DEFAULT_FROM_EMAIL=noreply@citypoint.local\n"
        "EMAIL_FILE_PATH=/opt/citypoint/var/mail_outbox\n"
        "# SMTP (variant II/III, daxili mail):\n"
        "# EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend\n"
        "# EMAIL_HOST=mail.citypoint.local\n"
        "# EMAIL_PORT=587\n"
        "\n"
        "SESSION_COOKIE_AGE=28800\n"
        "SESSION_SAVE_EVERY_REQUEST=1\n"
        "# Variant A (public HTTPS):\n"
        "SESSION_COOKIE_SECURE=1\n"
        "CSRF_COOKIE_SECURE=1\n"
        "SECURE_SSL_REDIRECT=0\n"
        "SECURE_HSTS_SECONDS=31536000\n"
        "# Variant B/C (HTTP daxili): SESSION/CSRF_SECURE=0\n"
        "\n"
        "AXTRAX_POLL_ON_START=0\n"
        "AXTRAX_POLL_INTERVAL=15\n"
        "TURNSTILE_MSSQL_HOST=172.31.104.10\n"
        "TURNSTILE_MSSQL_PORT=1433\n"
        "TURNSTILE_MSSQL_DATABASE=AxTrax1\n"
        "TURNSTILE_MSSQL_USER=ReadOnlyerp\n"
        "TURNSTILE_MSSQL_PASSWORD=CHANGE_ME\n"
        "EOF\n"
        "sudo chmod 600 /opt/citypoint/bin/prod/.env\n"
        "sudo chown citypoint:citypoint /opt/citypoint/bin/prod/.env",
    )

    add_heading(doc, "12.2 migrate, collectstatic, admin", 2)
    add_code(
        doc,
        "sudo -u citypoint -H bash <<'EOF'\n"
        "cd /opt/citypoint\n"
        "source .venv/bin/activate\n"
        "set -a\n"
        "source bin/prod/.env\n"
        "export POSTGRES_USER=cp_migrator\n"
        "export POSTGRES_PASSWORD=CHANGE_ME_MIGRATOR\n"
        "set +a\n"
        "python manage.py migrate --noinput\n"
        "python manage.py collectstatic --noinput\n"
        "EOF\n"
        "\n"
        "# Runtime üçün .env-də POSTGRES_USER=cp_app qalsın\n"
        "sudo -u citypoint -H bash -c 'cd /opt/citypoint && source .venv/bin/activate && set -a && source bin/prod/.env && set +a && python manage.py createsuperuser'\n"
        "\n"
        "sudo -u citypoint -H bash -c 'cd /opt/citypoint && source .venv/bin/activate && set -a && source bin/prod/.env && set +a && python manage.py invite_portal_user --email=office@tenant.az --company=COMPANY_SLUG --first-name=Office --last-name=Manager --base-url=https://portal.citypoint.az --send-email'",
    )

    # ========== SYSTEMD ==========
    add_heading(doc, "13. systemd xidmətləri (tam fayllar)", 1)
    add_code(
        doc,
        "sudo tee /etc/systemd/system/citypoint-web.service <<'EOF'\n"
        "[Unit]\n"
        "Description=City Point ERP/Portal (Gunicorn)\n"
        "After=network-online.target postgresql.service\n"
        "Wants=network-online.target\n"
        "Requires=postgresql.service\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=citypoint\n"
        "Group=citypoint\n"
        "WorkingDirectory=/opt/citypoint\n"
        "EnvironmentFile=/opt/citypoint/bin/prod/.env\n"
        "ExecStart=/opt/citypoint/.venv/bin/gunicorn config.wsgi:application \\\n"
        "  --bind 127.0.0.1:8000 --workers 3 --timeout 120 --access-logfile - --error-logfile -\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
        "EOF\n"
        "\n"
        "sudo tee /etc/systemd/system/citypoint-axtrax.service <<'EOF'\n"
        "[Unit]\n"
        "Description=City Point AxTrax poller\n"
        "After=network-online.target citypoint-web.service\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=citypoint\n"
        "Group=citypoint\n"
        "WorkingDirectory=/opt/citypoint\n"
        "EnvironmentFile=/opt/citypoint/bin/prod/.env\n"
        "ExecStart=/opt/citypoint/.venv/bin/python manage.py poll_axtrax\n"
        "Restart=always\n"
        "RestartSec=15\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
        "EOF\n"
        "\n"
        "sudo systemctl daemon-reload\n"
        "sudo systemctl enable --now citypoint-web citypoint-axtrax\n"
        "sudo systemctl status citypoint-web citypoint-axtrax --no-pager",
    )

    # ========== TLS ==========
    add_heading(doc, "14. TLS sertifikatları", 1)
    add_heading(doc, "14.1 Variant II/III — Let's Encrypt (certbot)", 2)
    add_code(
        doc,
        "sudo dnf install -y certbot python3-certbot-nginx\n"
        "sudo certbot --nginx -d portal.citypoint.az\n"
        "sudo certbot renew --dry-run",
    )
    add_heading(doc, "14.2 Variant I — air-gap: daxili CA və ya USB import", 2)
    add_code(
        doc,
        "# Build maşınında self-signed və ya korporativ CA ilə:\n"
        "openssl req -x509 -nodes -days 825 -newkey rsa:2048 \\\n"
        "  -keyout portal.key -out portal.crt \\\n"
        "  -subj '/CN=portal.citypoint.az'\n"
        "sudo cp portal.crt /etc/pki/tls/certs/portal.citypoint.az.crt\n"
        "sudo cp portal.key /etc/pki/tls/private/portal.citypoint.az.key\n"
        "sudo chmod 600 /etc/pki/tls/private/portal.citypoint.az.key",
    )

    # ========== NGINX ENABLE + SELINUX ==========
    add_heading(doc, "14.3 Nginx aktivləşdirmə + SELinux", 2)
    add_code(
        doc,
        "# Variant A: §3-dəki iki conf faylını yazın\n"
        "# Variant B: §4-dəki citypoint-internal.conf\n"
        "# Variant C: §4-dəki kimi yalnız erp.citypoint.local\n"
        "sudo nginx -t\n"
        "sudo systemctl enable --now nginx\n"
        "sudo systemctl reload nginx\n"
        "\n"
        "# SELinux: Nginx → Gunicorn (127.0.0.1:8000)\n"
        "sudo setsebool -P httpd_can_network_connect 1\n"
        "sudo setsebool -P httpd_read_user_content 1\n"
        "# static/media oxumaq üçün (lazım olarsa):\n"
        "sudo chcon -R -t httpd_sys_content_t /opt/citypoint/staticfiles /opt/citypoint/media\n"
        "# və ya: sudo semanage fcontext -a -t httpd_sys_content_t '/opt/citypoint/(staticfiles|media)(/.*)?'\n"
        "# sudo restorecon -Rv /opt/citypoint/staticfiles /opt/citypoint/media",
    )

    # ========== AXTRAX ==========
    add_heading(doc, "15. AxTrax inteqrasiyası (tam əmrlər)", 1)
    add_para(doc, "FreeTDS (pymssql) — /etc/freetds.conf nümunəsi:", bold=True)
    add_code(
        doc,
        "sudo tee /etc/freetds.conf <<'EOF'\n"
        "[global]\n"
        "    tds version = 7.4\n"
        "    client charset = UTF-8\n"
        "\n"
        "[axtrax]\n"
        "    host = 172.31.104.10\n"
        "    port = 1433\n"
        "    tds version = 7.4\n"
        "EOF",
    )
    add_code(
        doc,
        "# Şəbəkə yoxlama\n"
        "nc -zv 172.31.104.10 1433\n"
        "# və ya: timeout 3 bash -c 'echo >/dev/tcp/172.31.104.10/1433' && echo OK\n"
        "\n"
        "CP='sudo -u citypoint -H bash -c'\n"
        "RUN='cd /opt/citypoint && source .venv/bin/activate && set -a && source bin/prod/.env && set +a'\n"
        "\n"
        "$CP \"$RUN && python manage.py axtrax_sync_status\"\n"
        "$CP \"$RUN && python manage.py sync_axtrax_people --from-mssql\"\n"
        "$CP \"$RUN && python manage.py poll_axtrax --once\"\n"
        "$CP \"$RUN && python manage.py backfill_axtrax_events --from=2026-09-01\"\n"
        "\n"
        "sudo systemctl restart citypoint-axtrax\n"
        "sudo journalctl -u citypoint-axtrax -f\n"
        "# və ya: tail -f /opt/citypoint/var/axtrax_poller.log",
    )

    # ========== BACKUP ==========
    add_heading(doc, "16. Backup və restore (tam skriptlər)", 1)
    add_heading(doc, "16.1 .pgpass + backup skripti", 2)
    add_code(
        doc,
        "sudo -u citypoint tee /opt/citypoint/.pgpass <<'EOF'\n"
        "127.0.0.1:5432:citypoint:cp_app:CHANGE_ME_APP\n"
        "EOF\n"
        "sudo chmod 600 /opt/citypoint/.pgpass\n"
        "sudo chown citypoint:citypoint /opt/citypoint/.pgpass\n"
        "\n"
        "sudo tee /usr/local/bin/citypoint-backup.sh <<'EOF'\n"
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "STAMP=$(date +%Y%m%d-%H%M)\n"
        "OUT=/backup/citypoint\n"
        "mkdir -p \"$OUT\"\n"
        "export PGPASSFILE=/opt/citypoint/.pgpass\n"
        "pg_dump -h 127.0.0.1 -U cp_app -d citypoint | gzip > \"$OUT/db-$STAMP.sql.gz\"\n"
        "tar czf \"$OUT/media-$STAMP.tar.gz\" -C /opt/citypoint media\n"
        "# 14 gündən köhnə sil\n"
        "find \"$OUT\" -type f -mtime +14 -name 'db-*.sql.gz' -delete\n"
        "find \"$OUT\" -type f -mtime +14 -name 'media-*.tar.gz' -delete\n"
        "EOF\n"
        "sudo chmod 755 /usr/local/bin/citypoint-backup.sh\n"
        "\n"
        "sudo tee /etc/cron.d/citypoint-backup <<'EOF'\n"
        "SHELL=/bin/bash\n"
        "PATH=/usr/sbin:/usr/bin:/bin\n"
        "15 2 * * * citypoint /usr/local/bin/citypoint-backup.sh >> /backup/citypoint/backup.log 2>&1\n"
        "EOF\n"
        "# Bir dəfə əl ilə yoxlayın:\n"
        "sudo -u citypoint /usr/local/bin/citypoint-backup.sh\n"
        "ls -lh /backup/citypoint/",
    )
    add_heading(doc, "16.2 Restore (hadisə / drill)", 2)
    add_code(
        doc,
        "# 1) Yazıcıları dayandır\n"
        "sudo systemctl stop citypoint-web citypoint-axtrax\n"
        "\n"
        "# 2) DB bərpa (nümunə — ayrı test DB və ya prod)\n"
        "gunzip -c /backup/citypoint/db-YYYYMMDD-HHMM.sql.gz | \\\n"
        "  sudo -u postgres psql -d citypoint\n"
        "\n"
        "# 3) Media\n"
        "sudo -u citypoint tar xzf /backup/citypoint/media-YYYYMMDD-HHMM.tar.gz -C /opt/citypoint\n"
        "\n"
        "# 4) Xidmətləri qaldır\n"
        "sudo systemctl start citypoint-web citypoint-axtrax\n"
        "sudo systemctl status citypoint-web --no-pager",
    )

    # ========== LOGROTATE ==========
    add_heading(doc, "16.3 logrotate", 2)
    add_code(
        doc,
        "sudo tee /etc/logrotate.d/citypoint <<'EOF'\n"
        "/opt/citypoint/var/axtrax_poller.log {\n"
        "    weekly\n"
        "    rotate 8\n"
        "    compress\n"
        "    missingok\n"
        "    notifempty\n"
        "    copytruncate\n"
        "}\n"
        "/backup/citypoint/backup.log {\n"
        "    monthly\n"
        "    rotate 6\n"
        "    compress\n"
        "    missingok\n"
        "    notifempty\n"
        "}\n"
        "EOF",
    )

    # ========== PORT MATRIX ==========
    add_heading(doc, "17. Port matrix (variantlara görə)", 1)
    add_table(
        doc,
        ["Port", "Xidmət", "IN/OUT", "Variant A", "Variant B", "Variant C"],
        [
            ["443", "HTTPS Nginx", "IN", "Public portal + internal ERP", "VPN+LAN only", "LAN only"],
            ["80", "HTTP redirect", "IN", "Public→443", "LAN", "LAN"],
            ["8000", "Gunicorn", "IN", "127.0.0.1 only", "127.0.0.1", "127.0.0.1"],
            ["5432", "PostgreSQL", "IN", "Bağlı (localhost)", "Bağlı", "Bağlı"],
            ["1433", "AxTrax SQL", "OUT", "LAN", "LAN", "LAN"],
            ["22", "SSH", "IN", "Admin IP allowlist", "Admin IP", "Admin IP"],
        ],
    )

    # ========== UPDATE ==========
    add_heading(doc, "17.1 Yeniləmə proseduru (air-gap)", 2)
    add_code(
        doc,
        "# Build maşını: yeni zip + (lazım olsa) yeni wheelhouse → USB\n"
        "sudo systemctl stop citypoint-web citypoint-axtrax\n"
        "sudo -u citypoint /usr/local/bin/citypoint-backup.sh\n"
        "sudo unzip -o /mnt/usb/citypoint-app.zip -d /opt/citypoint\n"
        "sudo cp -a /mnt/usb/wheelhouse/. /opt/offline/wheelhouse/  # əgər dəyişibsə\n"
        "sudo -u citypoint -H bash <<'EOF'\n"
        "cd /opt/citypoint\n"
        "source .venv/bin/activate\n"
        "pip install --no-index --find-links=/opt/offline/wheelhouse -r requirements.txt\n"
        "set -a; source bin/prod/.env; export POSTGRES_USER=cp_migrator; export POSTGRES_PASSWORD=CHANGE_ME_MIGRATOR; set +a\n"
        "python manage.py migrate --noinput\n"
        "python manage.py collectstatic --noinput\n"
        "EOF\n"
        "sudo systemctl start citypoint-web citypoint-axtrax",
    )

    # ========== GO-LIVE ==========
    add_heading(doc, "18. Go-live yoxlama əmrləri", 1)
    add_code(
        doc,
        "curl -sI http://127.0.0.1:8000/login/ | head -1\n"
        "curl -sI https://portal.citypoint.az/login/ | head -1   # variant A\n"
        "curl -sI http://erp.citypoint.local/login/ | head -1    # variant B/C\n"
        "\n"
        "CP='sudo -u citypoint -H bash -c'\n"
        "RUN='cd /opt/citypoint && source .venv/bin/activate && set -a && source bin/prod/.env && set +a'\n"
        "$CP \"$RUN && python manage.py check --deploy\"\n"
        "$CP \"$RUN && python manage.py axtrax_sync_status\"\n"
        "\n"
        "sudo systemctl is-active citypoint-web citypoint-axtrax postgresql nginx chronyd\n"
        "sudo ss -lntp | egrep ':80|:443|:8000|:5432'\n"
        "# 8000 və 5432 yalnız 127.0.0.1 olmalıdır",
    )
    add_heading(doc, "18.1 Checklist", 2)
    for item in [
        "CP_ENV=production, SEED_DEMO=0, DJANGO_DEBUG=0",
        "Seçilmiş rezident variantı (A/B/C) firewall + Nginx + .env uyğundur",
        "Seçilmiş İnternet variantı (I/II/III) — runtime pip/dnf air-gap qaydasına uyğundur",
        "Postgres yalnız localhost; cp_app runtime; migrate cp_migrator ilə edilib",
        "AxTrax sync_status OK; people sync; test kart oxutma",
        "Backup cron yazır; restore drill planlaşdırılıb",
        "Reboot test: systemctl enable xidmətlər qalxır",
        "İkonlar/şriftlər CDN olmadan yüklənir (Brauzer DevTools Network)",
        "Invite: --base-url düzgün FQDN; və ya mail_outbox-dan link kopyalanır",
    ]:
        add_bullet(doc, f"[ ] {item}")

    # ========== TROUBLESHOOTING ==========
    add_heading(doc, "19. Troubleshooting", 1)
    add_table(
        doc,
        ["Simptom", "Yoxlama", "Həll"],
        [
            ["502 Bad Gateway", "journalctl -u citypoint-web -n 50", "Gunicorn; .env; migrate; SELinux bool"],
            ["CSRF 403", "CSRF_TRUSTED_ORIGINS", "https/http; Nginx X-Forwarded-Proto"],
            ["DisallowedHost", "ALLOWED_HOSTS", "portal/erp host əlavə et"],
            ["AxTrax boş", "nc 1433; journalctl -u citypoint-axtrax", "PASSWORD; firewall OUT; freetds"],
            ["pymssql ImportError", "ldd .venv/.../pymssql*.so", "freetds / freetds-libs RPM"],
            ["pip Internet istəyir", "pip install log", "--no-index --find-links=/opt/offline/wheelhouse"],
            ["Static 404", "ls /opt/citypoint/staticfiles", "collectstatic; nginx alias; SELinux"],
            ["DB connection refused", "ss -lntp | grep 5432", "listen_addresses=localhost; pg_hba"],
            ["Permission denied media", "ls -la /opt/citypoint/media", "chown citypoint; SELinux context"],
        ],
    )

    # ========== APPENDIX PATHS ==========
    add_heading(doc, "20. Əlavə — fayl yolları", 1)
    add_table(
        doc,
        ["Yol", "Məqsəd"],
        [
            ["/opt/citypoint", "Layihə kökü (USB zip)"],
            ["/opt/citypoint/bin/prod/.env", "Prod secret-lər (chmod 600)"],
            ["/opt/citypoint/.venv", "Python virtualenv"],
            ["/opt/citypoint/requirements.txt", "Python asılılıqları (aşağıda tam)"],
            ["/opt/citypoint/staticfiles", "collectstatic çıxışı"],
            ["/opt/citypoint/media", "Yükləmələr"],
            ["/opt/citypoint/var/mail_outbox", "CP_OFFLINE=1 mail faylları"],
            ["/opt/citypoint/var/axtrax_poller.log", "AxTrax poller log"],
            ["/etc/systemd/system/citypoint-web.service", "Gunicorn unit"],
            ["/etc/systemd/system/citypoint-axtrax.service", "AxTrax poller unit"],
            ["/etc/nginx/conf.d/*.conf", "Nginx vhost"],
            ["/etc/freetds.conf", "MSSQL client"],
            ["/usr/local/bin/citypoint-backup.sh", "Backup skripti"],
            ["/etc/cron.d/citypoint-backup", "Gündəlik backup"],
            ["/backup/citypoint", "DB/media backup"],
            ["/opt/offline/wheelhouse", "Offline pip wheels"],
            ["/opt/offline/rpms", "Offline dnf RPMs"],
        ],
    )

    # ========== FULL APPENDIX CODE ==========
    add_heading(doc, "22. Əlavə — TAM kod faylları (kopyala-yapışdır)", 1)
    add_para(
        doc,
        "Aşağıdakı bloklar bu sənədin yuxarıdakı bölmələri ilə eynidir, lakin NetAdmin üçün "
        "bir yerdə toplanıb. Hər faylı qeyd olunmuş yola yazın.",
        bold=True,
    )

    add_heading(doc, "22.1 requirements.txt (layihə kökü — USB zip-də olmalıdır)", 2)
    add_code(
        doc,
        "Django>=5.1,<5.3\n"
        "psycopg[binary]>=3.2\n"
        "gunicorn>=23.0\n"
        "python-dotenv>=1.0\n"
        "Pillow>=11.0\n"
        "whitenoise>=6.8\n"
        "pymssql>=2.3\n"
        "openpyxl>=3.1",
    )

    add_heading(doc, "22.2 /opt/citypoint/bin/prod/.env (native prod — TAM)", 2)
    add_code(
        doc,
        "CP_ENV=production\n"
        "CP_OFFLINE=1\n"
        "DJANGO_SECRET_KEY=REPLACE_WITH_STRONG_RANDOM\n"
        "DJANGO_DEBUG=0\n"
        "SEED_DEMO=0\n"
        "\n"
        "# === Variant A nümunə (public portal + daxili ERP) ===\n"
        "DJANGO_ALLOWED_HOSTS=portal.citypoint.az,erp.citypoint.local,10.20.30.40\n"
        "DJANGO_CSRF_TRUSTED_ORIGINS=https://portal.citypoint.az,https://erp.citypoint.local\n"
        "SESSION_COOKIE_SECURE=1\n"
        "CSRF_COOKIE_SECURE=1\n"
        "SECURE_SSL_REDIRECT=0\n"
        "SECURE_HSTS_SECONDS=31536000\n"
        "\n"
        "# === Variant B/C üçün yuxarıdakı yerinə (HTTP daxili) ===\n"
        "# DJANGO_ALLOWED_HOSTS=erp.citypoint.local,portal.citypoint.local,10.20.30.40\n"
        "# DJANGO_CSRF_TRUSTED_ORIGINS=http://erp.citypoint.local,http://portal.citypoint.local\n"
        "# SESSION_COOKIE_SECURE=0\n"
        "# CSRF_COOKIE_SECURE=0\n"
        "# SECURE_SSL_REDIRECT=0\n"
        "# SECURE_HSTS_SECONDS=0\n"
        "\n"
        "POSTGRES_DB=citypoint\n"
        "POSTGRES_USER=cp_app\n"
        "POSTGRES_PASSWORD=CHANGE_ME_APP\n"
        "POSTGRES_HOST=127.0.0.1\n"
        "POSTGRES_PORT=5432\n"
        "\n"
        "DEFAULT_FROM_EMAIL=noreply@citypoint.local\n"
        "EMAIL_FILE_PATH=/opt/citypoint/var/mail_outbox\n"
        "# EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend\n"
        "# EMAIL_HOST=mail.citypoint.local\n"
        "# EMAIL_PORT=587\n"
        "# EMAIL_HOST_USER=\n"
        "# EMAIL_HOST_PASSWORD=\n"
        "# EMAIL_USE_TLS=1\n"
        "\n"
        "SESSION_COOKIE_AGE=28800\n"
        "SESSION_SAVE_EVERY_REQUEST=1\n"
        "\n"
        "# Native-da AxTrax ayrı systemd unit-dir — web startında poller lazım deyil\n"
        "AXTRAX_POLL_ON_START=0\n"
        "AXTRAX_BOOTSTRAP_ON_START=0\n"
        "AXTRAX_POLL_INTERVAL=15\n"
        "AXTRAX_PEOPLE_SYNC_INTERVAL=300\n"
        "TURNSTILE_MSSQL_HOST=172.31.104.10\n"
        "TURNSTILE_MSSQL_PORT=1433\n"
        "TURNSTILE_MSSQL_DATABASE=AxTrax1\n"
        "TURNSTILE_MSSQL_USER=ReadOnlyerp\n"
        "TURNSTILE_MSSQL_PASSWORD=CHANGE_ME",
    )

    add_heading(doc, "22.3 PostgreSQL — bootstrap SQL (TAM)", 2)
    add_code(
        doc,
        "CREATE DATABASE citypoint;\n"
        "CREATE ROLE cp_migrator LOGIN PASSWORD 'CHANGE_ME_MIGRATOR';\n"
        "CREATE ROLE cp_app LOGIN PASSWORD 'CHANGE_ME_APP';\n"
        "CREATE ROLE cp_readonly LOGIN PASSWORD 'CHANGE_ME_READONLY';\n"
        "GRANT CONNECT ON DATABASE citypoint TO cp_migrator, cp_app, cp_readonly;\n"
        "\\c citypoint\n"
        "GRANT USAGE ON SCHEMA public TO cp_migrator, cp_app, cp_readonly;\n"
        "GRANT ALL ON SCHEMA public TO cp_migrator;\n"
        "\n"
        "-- migrate-dən SONRA:\n"
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cp_app;\n"
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cp_app;\n"
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO cp_readonly;\n"
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cp_readonly;\n"
        "ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public\n"
        "  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cp_app;\n"
        "ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public\n"
        "  GRANT USAGE, SELECT ON SEQUENCES TO cp_app;\n"
        "ALTER DEFAULT PRIVILEGES FOR ROLE cp_migrator IN SCHEMA public\n"
        "  GRANT SELECT ON TABLES TO cp_readonly;",
    )

    add_heading(doc, "22.4 /etc/systemd/system/citypoint-web.service (TAM)", 2)
    add_code(
        doc,
        "[Unit]\n"
        "Description=City Point ERP/Portal (Gunicorn)\n"
        "After=network-online.target postgresql.service\n"
        "Wants=network-online.target\n"
        "Requires=postgresql.service\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=citypoint\n"
        "Group=citypoint\n"
        "WorkingDirectory=/opt/citypoint\n"
        "EnvironmentFile=/opt/citypoint/bin/prod/.env\n"
        "ExecStart=/opt/citypoint/.venv/bin/gunicorn config.wsgi:application "
        "--bind 127.0.0.1:8000 --workers 3 --timeout 120 "
        "--access-logfile - --error-logfile -\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target",
    )

    add_heading(doc, "22.5 /etc/systemd/system/citypoint-axtrax.service (TAM)", 2)
    add_code(
        doc,
        "[Unit]\n"
        "Description=City Point AxTrax poller\n"
        "After=network-online.target postgresql.service\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=citypoint\n"
        "Group=citypoint\n"
        "WorkingDirectory=/opt/citypoint\n"
        "EnvironmentFile=/opt/citypoint/bin/prod/.env\n"
        "ExecStart=/opt/citypoint/.venv/bin/python manage.py poll_axtrax\n"
        "Restart=always\n"
        "RestartSec=15\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target",
    )

    add_heading(doc, "22.6 Nginx — Variant A portal public (TAM)", 2)
    add_code(
        doc,
        "# /etc/nginx/conf.d/citypoint-portal-public.conf\n"
        "limit_req_zone $binary_remote_addr zone=cp_login:10m rate=5r/m;\n"
        "\n"
        "server {\n"
        "    listen 443 ssl http2;\n"
        "    server_name portal.citypoint.az;\n"
        "    ssl_certificate     /etc/pki/tls/certs/portal.citypoint.az.crt;\n"
        "    ssl_certificate_key /etc/pki/tls/private/portal.citypoint.az.key;\n"
        "    client_max_body_size 50M;\n"
        "\n"
        "    location /static/ { alias /opt/citypoint/staticfiles/; }\n"
        "    location /media/  { alias /opt/citypoint/media/; }\n"
        "\n"
        "    location /erp/      { return 404; }\n"
        "    location /admin/    { return 404; }\n"
        "    location /security/ { return 404; }\n"
        "\n"
        "    location /login/ {\n"
        "        limit_req zone=cp_login burst=10 nodelay;\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "    }\n"
        "\n"
        "    location / {\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "    }\n"
        "}\n"
        "server {\n"
        "    listen 80;\n"
        "    server_name portal.citypoint.az;\n"
        "    return 301 https://$host$request_uri;\n"
        "}",
    )

    add_heading(doc, "22.7 Nginx — Variant A ERP internal (TAM)", 2)
    add_code(
        doc,
        "# /etc/nginx/conf.d/citypoint-erp-internal.conf\n"
        "server {\n"
        "    listen 443 ssl http2;\n"
        "    server_name erp.citypoint.local;\n"
        "    ssl_certificate     /etc/pki/tls/certs/erp.citypoint.local.crt;\n"
        "    ssl_certificate_key /etc/pki/tls/private/erp.citypoint.local.key;\n"
        "    client_max_body_size 50M;\n"
        "    location /static/ { alias /opt/citypoint/staticfiles/; }\n"
        "    location /media/  { alias /opt/citypoint/media/; }\n"
        "    location / {\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "    }\n"
        "}",
    )

    add_heading(doc, "22.8 Nginx — Variant B/C daxili HTTP (TAM)", 2)
    add_code(
        doc,
        "# /etc/nginx/conf.d/citypoint-internal.conf\n"
        "server {\n"
        "    listen 80;\n"
        "    server_name portal.citypoint.local erp.citypoint.local;\n"
        "    client_max_body_size 50M;\n"
        "    location /static/ { alias /opt/citypoint/staticfiles/; }\n"
        "    location /media/  { alias /opt/citypoint/media/; }\n"
        "    location / {\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    }\n"
        "}",
    )

    add_heading(doc, "22.9 Invite / admin əmrləri", 2)
    add_code(
        doc,
        "CP='sudo -u citypoint -H bash -c'\n"
        "RUN='cd /opt/citypoint && source .venv/bin/activate && set -a && source bin/prod/.env && set +a'\n"
        "\n"
        "# Superuser (bir dəfə)\n"
        "$CP \"$RUN && python manage.py createsuperuser\"\n"
        "\n"
        "# Rezident portal invite\n"
        "$CP \"$RUN && python manage.py invite_portal_user \\\n"
        "  --email=office@tenant.az --company=COMPANY_SLUG \\\n"
        "  --first-name=Office --last-name=Manager \\\n"
        "  --base-url=https://portal.citypoint.az --send-email\"\n"
        "\n"
        "# Mail göndərilməyibsə:\n"
        "ls -lt /opt/citypoint/var/mail_outbox | head\n"
        "\n"
        "# Uğursuz invite mailləri yenidən\n"
        "$CP \"$RUN && python manage.py retry_invite_emails\"",
    )

    add_heading(doc, "22.10 USB paket checklist (build → prod)", 2)
    add_table(
        doc,
        ["USB yolu", "Məzmun", "Prod-da hara"],
        [
            ["citypoint-app.zip", "Django repo (git archive)", "/opt/citypoint"],
            ["wheelhouse/", "pip download nəticəsi", "/opt/offline/wheelhouse"],
            ["rpms/", "dnf download + createrepo_c", "/opt/offline/rpms"],
            ["certs/ (opsional)", "portal/erp .crt/.key", "/etc/pki/tls/..."],
            ["Bu Word sənədi", "NetAdmin rəhbəri", "ops laptop / print"],
        ],
    )

    add_heading(doc, "23. Qəbul imzası", 1)
    add_table(
        doc,
        ["Rol", "Ad", "Tarix", "İmza"],
        [
            ["NetAdmin (İnternet yox / variant təsdiqi)", "", "", ""],
            ["SysAdmin (native quraşdırma)", "", "", ""],
            ["ERP ops (migrate / invite / smoke)", "", "", ""],
            ["Rəhbərlik", "", "", ""],
        ],
    )

    add_para(
        doc,
        "— City Point ERP · NetAdmin rəhbəri v3.0 · ÖZÜNÜ-KİFAYƏT · Confidential —",
        align=WD_ALIGN_PARAGRAPH.CENTER,
        size=9,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    doc.save(OUT_LEGACY)
    print(f"Wrote {OUT}")
    print(f"Wrote {OUT_LEGACY}")


if __name__ == "__main__":
    build()
