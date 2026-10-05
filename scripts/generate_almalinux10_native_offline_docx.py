#!/usr/bin/env python3
"""Generate AlmaLinux 10 City Point ERP native (NO Docker) offline deploy guide as Word."""

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
    / "CityPoint_AlmaLinux10_Native_Offline_Rehberi.docx"
)


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


def add_para(doc, text, *, bold=False, size=11, space_after=8):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
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
    run.font.size = Pt(9)
    return p


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        run = hdr[i].paragraphs[0].add_run(h)
        set_run_font(run, bold=True, size=10)
    for r_i, row in enumerate(rows):
        cells = table.rows[r_i + 1].cells
        for c_i, val in enumerate(row):
            cells[c_i].text = ""
            run = cells[c_i].paragraphs[0].add_run(str(val))
            set_run_font(run, size=10)
    doc.add_paragraph()
    return table


def build():
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("CITY POINT ERP / PORTAL")
    set_run_font(r, size=22, bold=True, color=RGBColor(0x1F, 0x49, 0x7D))

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run(
        "AlmaLinux 10 — Docker OLMADAN · Tam offline (İnternetsiz) quraşdırma rəhbəri"
    )
    set_run_font(r, size=13, bold=True)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = meta.add_run(
        f"Versiya: 1.0  ·  Tarix: {date.today().isoformat()}  ·  "
        "Native: PostgreSQL + Python venv + Gunicorn + systemd + (opsional) Nginx"
    )
    set_run_font(r, size=9, color=RGBColor(0x64, 0x74, 0x8B))

    warn = doc.add_paragraph()
    run = warn.add_run(
        "ƏSAS ŞƏRT: Prod serverdə İNTERNET YOXDUR. Go-live və istismar zamanı "
        "dnf/pip/docker pull işləməyəcək. Bütün RPM, Python wheel və kod "
        "əvvəlcədən (İnternet olan ayrı maşında) hazırlanıb USB/NAS ilə gətirilir."
    )
    set_run_font(run, size=11, bold=True, color=RGBColor(0x9A, 0x34, 0x1B))

    add_para(
        doc,
        "Bu sənəd Docker istifadəsi ETMƏDƏN City Point ERP/Portal-ı AlmaLinux 10 "
        "üzərində LAN/air-gapped modeldə quraşdırmaq üçündür. Docker Guide "
        "(CityPoint_AlmaLinux10_Deploy_Rehberi.docx) bu sənədi əvəz etmir — "
        "City Point serverində İnternet olmayacağı üçün Docker Hub asılılığı "
        "risklidir; native quraşdırma tövsiyə olunan yoldur.",
    )

    # ---- 1 ----
    add_heading(doc, "1. Niyə Docker yox — native?", 1)
    add_bullet(doc, "Serverdə İnternet yox → Docker Hub-dan image çəkilə bilməz")
    add_bullet(doc, "docker save/load mümkündür, amma əlavə mürəkkəblik və böyük tar faylları")
    add_bullet(doc, "Native: OS RPM + pip wheelhouse — bir dəfə paketləyib USB ilə gətirirsiniz")
    add_bullet(doc, "systemd ilə web (Gunicorn) və AxTrax poller ayrı xidmət kimi idarə olunur")
    add_bullet(doc, "PostgreSQL AlmaLinux paketi / offline RPM — Docker volume lazım deyil")

    add_para(doc, "Hədəf arxitektura:", bold=True)
    add_code(
        doc,
        "[ Resident / Staff PC ] → LAN → Nginx (:80/:443) və ya birbaşa Gunicorn (:8000)\n"
        "                                      ↓\n"
        "                         Python venv + Django + Gunicorn  (systemd)\n"
        "                                      ↓\n"
        "                         PostgreSQL 16  (localhost :5432, firewall bağlı)\n"
        "                                      +\n"
        "                         AxTrax poller  (systemd) → AxTrax MS SQL LAN :1433",
    )

    # ---- 2 ----
    add_heading(doc, "2. Server resursları", 1)
    add_table(
        doc,
        ["Resurs", "Minimum (pilot)", "Tövsiyə", "Qeyd"],
        [
            ["CPU", "4 vCPU", "8 vCPU", "Gunicorn + poller + Postgres"],
            ["RAM", "8 GB", "16 GB", "Postgres shared_buffers üçün"],
            ["Disk", "100 GB SSD", "200+ GB", "DB + media + /backup + wheelhouse arxiv"],
            ["OS", "AlmaLinux 10 x86_64", "AlmaLinux 10", "İnternetsiz quraşdırılmış ISO"],
            ["Şəbəkə", "1 Gbit LAN, statik IP", "1 Gbit", "AxTrax-a marşrut; İnternet uplink YOX"],
        ],
    )

    # ---- 3 ----
    add_heading(doc, "3. İki maşın modeli (mütləq)", 1)
    add_para(
        doc,
        "Prod server heç vaxt İnternetə qoşulmur. Paketləri hazırlayan maşın ayrıdır.",
        bold=True,
    )
    add_table(
        doc,
        ["Maşın", "İnternet", "Rol"],
        [
            [
                "Build / paket maşını",
                "VAR (müvəqqəti)",
                "RPM download, pip download wheelhouse, repo zip",
            ],
            [
                "City Point prod (AlmaLinux 10)",
                "YOX",
                "USB/NAS-dan quraşdırma; yalnız LAN (brauzer + AxTrax)",
            ],
        ],
    )
    add_para(doc, "USB/NAS-da gətirilən paket dəsti (minimum):", bold=True)
    add_bullet(doc, "citypoint-app.zip — repo kodu")
    add_bullet(doc, "rpms/ — PostgreSQL, Python, nginx, freetds/openssl və asılılıqlar")
    add_bullet(doc, "wheelhouse/ — requirements.txt üçün bütün .whl / .tar.gz")
    add_bullet(doc, "env.template → serverdə .env (secret-lər ayrı, etibarlı kanal)")
    add_bullet(doc, "Bu Word rəhbəri + checklist çapı")

    # ---- 4 ----
    add_heading(doc, "4. Əvvəlcədən toplanmalı məlumatlar", 1)
    add_table(
        doc,
        ["#", "Məlumat", "Nümunə"],
        [
            ["1", "Hostname / IP", "erp.citypoint.local / 10.x.x.x"],
            ["2", "Portal/ERP URL", "http://erp.citypoint.local"],
            ["3", "AxTrax SQL", "172.31.104.10:1433 / AxTrax1"],
            ["4", "AxTrax RO user/pass", "ReadOnlyerp / (secret)"],
            ["5", "Mail", "CP_OFFLINE=1 + link kopyalama (SMTP yoxdursa)"],
            ["6", "DJANGO_SECRET_KEY", "güclü təsadüfi"],
            ["7", "Postgres şifrələri", "cp_migrator / cp_app / cp_readonly"],
            ["8", "Backup yolu", "/backup/citypoint və ya NAS"],
            ["9", "NTP", "daxili DC / chrony (public NTP olmaya bilər)"],
            ["10", "Firewall", "80/443 və ya 8000 IN; 5432 XARİCİDEN bağlı; 1433 OUT AxTrax"],
        ],
    )

    # ---- 5 ----
    add_heading(doc, "5. Build maşınında paket hazırlığı (İnternet VAR)", 1)
    add_heading(doc, "5.1. Tətbiq kodu", 2)
    add_code(
        doc,
        "# Build maşınında\n"
        "git clone <repo> city-point-system\n"
        "# və ya zip/export\n"
        "cd city-point-system\n"
        "zip -r /media/usb/citypoint-app.zip . -x '*.git*' -x '*__pycache__*' -x 'media/*'",
    )

    add_heading(doc, "5.2. Python wheelhouse (PyPI offline)", 2)
    add_para(
        doc,
        "Prod serverdə pip install İnternetə çıxmayacaq. Bütün asılılıqları "
        "wheel kimi yükləyin (Linux x86_64, Python 3.12 ilə uyğun):",
    )
    add_code(
        doc,
        "# Linux build maşınında (AlmaLinux 10 və ya uyğun glibc, Python 3.12)\n"
        "python3.12 -m venv /tmp/cp-build-venv\n"
        "source /tmp/cp-build-venv/bin/activate\n"
        "pip install --upgrade pip wheel\n"
        "mkdir -p /media/usb/wheelhouse\n"
        "pip download -r requirements.txt -d /media/usb/wheelhouse\n"
        "# pymssql / psycopg[binary] / Pillow üçün manylinux wheel-lər gəlməlidir\n"
        "ls /media/usb/wheelhouse | wc -l",
    )
    add_para(
        doc,
        "QEYD: Wheel-ləri Windows-da yükləmək risklidir (platform uyğunsuzluğu). "
        "Wheelhouse-u AlmaLinux 10 (və ya eyni glibc) maşında hazırlayın.",
        bold=True,
    )

    add_heading(doc, "5.3. RPM paketləri (dnf download / createrepo)", 2)
    add_para(doc, "Prod serverdə lazım olan tipik paketlər:", bold=True)
    add_bullet(doc, "python3.12 (və ya AlmaLinux 10-da mövcud python3), python3-pip, python3-devel")
    add_bullet(doc, "postgresql16-server, postgresql16, postgresql16-contrib (versiya IT mirror-a görə)")
    add_bullet(doc, "nginx (opsional reverse proxy)")
    add_bullet(doc, "firewalld, chrony, git (opsional), unzip, tar, gzip")
    add_bullet(doc, "freetds və ya pymssql üçün lazım olan runtime lib-lər (libsybdb və s.)")
    add_bullet(doc, "gcc / openssl-devel — yalnız wheel build lazımdırsa; binary wheel varsa tələb azalır")
    add_code(
        doc,
        "# Build maşınında (AlmaLinux 10, İnternet/mirror var):\n"
        "sudo dnf install -y 'dnf-command(download)' createrepo_c\n"
        "mkdir -p /media/usb/rpms && cd /media/usb/rpms\n"
        "sudo dnf download --resolve --arch=x86_64 \\\n"
        "  python3 python3-pip python3-devel \\\n"
        "  postgresql-server postgresql postgresql-contrib \\\n"
        "  nginx firewalld chrony unzip tar gzip \\\n"
        "  freetds freetds-libs openssl-libs\n"
        "# Paket adları AlmaLinux 10 repo-da fərqlənə bilər — dnf search ilə təsdiq edin\n"
        "createrepo_c .\n"
        "# USB-də: /media/usb/rpms/  (local repo)",
    )
    add_para(
        doc,
        "İnternet olan build maşını ilə prod eyni major OS (AlmaLinux 10) olmalıdır ki, "
        "RPM asılılıqları uyğun gəlsin.",
    )

    # ---- 6 ----
    add_heading(doc, "6. Prod server — OS (İnternet YOX)", 1)
    add_heading(doc, "6.1. AlmaLinux 10 quraşdırma", 2)
    add_bullet(doc, "ISO ilə Minimal/Server quraşdırın (İnternet tələb olunmur)")
    add_bullet(doc, "Statik IP, hostname, Asia/Baku timezone")
    add_bullet(doc, "Yalnız LAN; İnternet uplink qoşulmasın")
    add_bullet(doc, "citypoint istifadəçisi + sudo")

    add_heading(doc, "6.2. Offline RPM quraşdırma", 2)
    add_code(
        doc,
        "sudo mkdir -p /opt/offline/rpms\n"
        "# USB-dən köçürün\n"
        "sudo cp -a /mnt/usb/rpms/* /opt/offline/rpms/\n"
        "\n"
        "# Lokal repo faylı\n"
        "sudo tee /etc/yum.repos.d/citypoint-offline.repo <<'EOF'\n"
        "[citypoint-offline]\n"
        "name=CityPoint Offline RPMs\n"
        "baseurl=file:///opt/offline/rpms\n"
        "enabled=1\n"
        "gpgcheck=0\n"
        "EOF\n"
        "\n"
        "sudo dnf clean all\n"
        "sudo dnf --disablerepo='*' --enablerepo=citypoint-offline install -y \\\n"
        "  python3 python3-pip python3-devel \\\n"
        "  postgresql-server postgresql postgresql-contrib \\\n"
        "  nginx firewalld chrony unzip tar gzip freetds freetds-libs\n"
        "# Paket adlarını USB-dəki real RPM-lərə uyğun düzəldin",
    )

    add_heading(doc, "6.3. Vaxt və firewall", 2)
    add_code(
        doc,
        "sudo systemctl enable --now chronyd\n"
        "timedatectl status   # daxili NTP\n"
        "\n"
        "sudo systemctl enable --now firewalld\n"
        "sudo firewall-cmd --permanent --add-service=http\n"
        "sudo firewall-cmd --permanent --add-service=https\n"
        "# və ya birbaşa Gunicorn:\n"
        "# sudo firewall-cmd --permanent --add-port=8000/tcp\n"
        "sudo firewall-cmd --reload\n"
        "# 5432 heç vaxt LAN-a açıq olmamalıdır",
    )

    # ---- 7 ----
    add_heading(doc, "7. PostgreSQL (native)", 1)
    add_code(
        doc,
        "sudo postgresql-setup --initdb   # və ya pg_ctl init (versiyaya görə)\n"
        "sudo systemctl enable --now postgresql\n"
        "\n"
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
    add_para(
        doc,
        "pg_hba.conf: yalnız local/127.0.0.1 scram-sha-256. "
        "Ətraflı: docs/security/postgres-roles.md. "
        "Migrate-dən sonra cədvəl DML grant-ları cp_app üçün verilməlidir.",
    )
    add_code(
        doc,
        "# listen_addresses = 'localhost'  (postgresql.conf)\n"
        "# host citypoint cp_app 127.0.0.1/32 scram-sha-256",
    )

    # ---- 8 ----
    add_heading(doc, "8. Tətbiq quraşdırması (venv + offline pip)", 1)
    add_heading(doc, "8.1. Kod və kataloqlar", 2)
    add_code(
        doc,
        "sudo mkdir -p /opt/citypoint /opt/offline/wheelhouse /backup/citypoint\n"
        "sudo useradd -r -m -d /opt/citypoint -s /bin/bash citypoint || true\n"
        "sudo unzip /mnt/usb/citypoint-app.zip -d /opt/citypoint\n"
        "sudo cp -a /mnt/usb/wheelhouse/* /opt/offline/wheelhouse/\n"
        "sudo chown -R citypoint:citypoint /opt/citypoint /backup/citypoint",
    )

    add_heading(doc, "8.2. Virtualenv + offline install", 2)
    add_code(
        doc,
        "sudo -u citypoint -H bash <<'EOF'\n"
        "cd /opt/citypoint\n"
        "python3 -m venv /opt/citypoint/.venv\n"
        "source /opt/citypoint/.venv/bin/activate\n"
        "pip install --no-index --find-links=/opt/offline/wheelhouse -r requirements.txt\n"
        "mkdir -p media staticfiles var/mail_outbox var\n"
        "EOF",
    )
    add_para(
        doc,
        "Uğur: pip heç bir 'Looking in indexes: https://pypi.org' uğursuz cəhdi etməməlidir "
        "(--no-index). Əks halda wheelhouse natamamdır — build maşınında yenidən download edin.",
        bold=True,
    )

    add_heading(doc, "8.3. .env (prod)", 2)
    add_code(
        doc,
        "sudo -u citypoint tee /opt/citypoint/bin/prod/.env <<'EOF'\n"
        "CP_ENV=production\n"
        "CP_OFFLINE=1\n"
        "DJANGO_SECRET_KEY=CHANGE_ME_STRONG\n"
        "DJANGO_DEBUG=0\n"
        "DJANGO_ALLOWED_HOSTS=erp.citypoint.local,10.x.x.x\n"
        "DJANGO_CSRF_TRUSTED_ORIGINS=http://erp.citypoint.local\n"
        "POSTGRES_DB=citypoint\n"
        "POSTGRES_USER=cp_app\n"
        "POSTGRES_PASSWORD=CHANGE_ME_APP\n"
        "POSTGRES_HOST=127.0.0.1\n"
        "POSTGRES_PORT=5432\n"
        "SEED_DEMO=0\n"
        "DEFAULT_FROM_EMAIL=noreply@citypoint.local\n"
        "EMAIL_FILE_PATH=/opt/citypoint/var/mail_outbox\n"
        "SESSION_COOKIE_AGE=28800\n"
        "SESSION_COOKIE_SECURE=0\n"
        "CSRF_COOKIE_SECURE=0\n"
        "SECURE_SSL_REDIRECT=0\n"
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
    add_para(
        doc,
        "AXTRAX_POLL_ON_START=0: native quraşdırmada poller ayrı systemd unit ilə işləyir "
        "(aşağıda). POSTGRES_HOST=127.0.0.1 (Docker-dakı 'db' hostname yoxdur).",
        bold=True,
    )

    add_heading(doc, "8.4. Migrate və collectstatic", 2)
    add_code(
        doc,
        "# Bir dəfəlik migrate — cp_migrator ilə (müvəqqəti .env və ya DATABASE_URL)\n"
        "sudo -u citypoint -H bash <<'EOF'\n"
        "cd /opt/citypoint\n"
        "source .venv/bin/activate\n"
        "export $(grep -v '^#' bin/prod/.env | xargs)\n"
        "# migrate üçün migrator user (nümunə):\n"
        "export POSTGRES_USER=cp_migrator\n"
        "export POSTGRES_PASSWORD=CHANGE_ME_MIGRATOR\n"
        "python manage.py migrate --noinput\n"
        "python manage.py collectstatic --noinput\n"
        "EOF\n"
        "\n"
        "# Sonra psql ilə cp_app-ə DML grant (postgres-roles.md)",
    )

    add_heading(doc, "8.5. İlk admin / portal invite", 2)
    add_code(
        doc,
        "cd /opt/citypoint && source .venv/bin/activate\n"
        "export $(grep -v '^#' bin/prod/.env | xargs)\n"
        "python manage.py createsuperuser\n"
        "python manage.py invite_portal_user \\\n"
        "  --email=office@tenant.az --company=<slug> \\\n"
        "  --first-name=Office --last-name=Manager \\\n"
        "  --base-url=http://erp.citypoint.local --send-email\n"
        "# CP_OFFLINE=1: link var/mail_outbox və ya konsolda — admin kopyalayıb verir",
    )

    # ---- 9 ----
    add_heading(doc, "9. systemd xidmətləri (Docker əvəzinə)", 1)
    add_heading(doc, "9.1. Gunicorn — citypoint-web.service", 2)
    add_code(
        doc,
        "sudo tee /etc/systemd/system/citypoint-web.service <<'EOF'\n"
        "[Unit]\n"
        "Description=City Point ERP Gunicorn\n"
        "After=network.target postgresql.service\n"
        "Requires=postgresql.service\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=citypoint\n"
        "Group=citypoint\n"
        "WorkingDirectory=/opt/citypoint\n"
        "EnvironmentFile=/opt/citypoint/bin/prod/.env\n"
        "ExecStart=/opt/citypoint/.venv/bin/gunicorn config.wsgi:application \\\n"
        "  --bind 127.0.0.1:8000 --workers 3 --timeout 120\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
        "EOF",
    )

    add_heading(doc, "9.2. AxTrax poller — citypoint-axtrax.service", 2)
    add_code(
        doc,
        "sudo tee /etc/systemd/system/citypoint-axtrax.service <<'EOF'\n"
        "[Unit]\n"
        "Description=City Point AxTrax poller\n"
        "After=network.target citypoint-web.service\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=citypoint\n"
        "Group=citypoint\n"
        "WorkingDirectory=/opt/citypoint\n"
        "EnvironmentFile=/opt/citypoint/bin/prod/.env\n"
        "ExecStart=/opt/citypoint/.venv/bin/python manage.py poll_axtrax\n"
        "Restart=always\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
        "EOF\n"
        "\n"
        "sudo systemctl daemon-reload\n"
        "sudo systemctl enable --now citypoint-web citypoint-axtrax\n"
        "sudo systemctl status citypoint-web citypoint-axtrax",
    )
    add_para(
        doc,
        "Windows Scheduled Task lazım deyil. Poller LAN üzərindən AxTrax MS SQL oxuyur; "
        "İnternet tələb olunmur. Status: python manage.py axtrax_sync_status",
    )

    # ---- 10 ----
    add_heading(doc, "10. Nginx (tövsiyə) — LAN brauzerlər üçün :80", 1)
    add_code(
        doc,
        "sudo tee /etc/nginx/conf.d/citypoint.conf <<'EOF'\n"
        "server {\n"
        "    listen 80;\n"
        "    server_name erp.citypoint.local;\n"
        "    client_max_body_size 50M;\n"
        "\n"
        "    location /static/ {\n"
        "        alias /opt/citypoint/staticfiles/;\n"
        "    }\n"
        "    location /media/ {\n"
        "        alias /opt/citypoint/media/;\n"
        "    }\n"
        "    location / {\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    }\n"
        "}\n"
        "EOF\n"
        "sudo systemctl enable --now nginx\n"
        "sudo nginx -t && sudo systemctl reload nginx",
    )
    add_para(
        doc,
        "Daxili HTTPS lazımdırsa — daxili CA sertifikatı (Let's Encrypt İnternet tələb edir, "
        "air-gap-də yoxdur). CSRF origins https:// ilə uyğunlaşdırın.",
    )

    # ---- 11 ----
    add_heading(doc, "11. AxTrax — offline LAN", 1)
    add_bullet(doc, "Hostdan: nc -vz 172.31.104.10 1433 (və ya telnet)")
    add_bullet(doc, "TURNSTILE_MSSQL_* yalnız .env-də; git-ə yazılmasın")
    add_bullet(doc, "axtrax_sync_status hər gün yoxlanılsın")
    add_bullet(doc, "Tarixi doldurma: python manage.py backfill_axtrax_events --from=YYYY-MM-DD")
    add_bullet(doc, "İnternet / cloud sync yoxdur — yalnız LAN RO SQL")

    # ---- 12 ----
    add_heading(doc, "12. Backup / restore (native)", 1)
    add_code(
        doc,
        "# /etc/cron.d/citypoint-backup\n"
        "15 2 * * * citypoint /usr/bin/pg_dump -h 127.0.0.1 -U cp_app citypoint \\\n"
        "  | gzip > /backup/citypoint/db-$(date +\\%Y\\%m\\%d).sql.gz\n"
        "30 2 * * * citypoint tar czf /backup/citypoint/media-$(date +\\%Y\\%m\\%d).tar.gz \\\n"
        "  -C /opt/citypoint media",
    )
    add_para(
        doc,
        "PGPASSWORD .pgpass ilə (~citypoint/.pgpass, chmod 600). "
        "Restore drill: ayrı DB adına bərpa + login smoke. "
        "Backup etibarlı deyil, əgər restore sınağı yoxdursa.",
        bold=True,
    )

    # ---- 13 ----
    add_heading(doc, "13. Yeniləmə (İnternetsiz)", 1)
    add_bullet(doc, "Build maşınında yeni kod zip + lazım olsa yeni wheelhouse")
    add_bullet(doc, "USB → /opt/citypoint (backup əvvəl!)")
    add_bullet(doc, "pip install --no-index --find-links=... -r requirements.txt")
    add_bullet(doc, "migrate (cp_migrator) + collectstatic")
    add_bullet(doc, "systemctl restart citypoint-web citypoint-axtrax")
    add_bullet(doc, "Rollback: əvvəlki zip + DB dump + restart")

    # ---- 14 ----
    add_heading(doc, "14. Təhlükəsizlik (air-gap)", 1)
    add_bullet(doc, "SEED_DEMO=0, DEBUG=0, güclü SECRET_KEY")
    add_bullet(doc, "CDN yox — yalnız /static/ (Whitenoise / Nginx)")
    add_bullet(doc, "Runtime-da pip/dnf İnternetə çıxmır")
    add_bullet(doc, "Postgres yalnız localhost; 5432 firewall-da bağlı")
    add_bullet(doc, ".env chmod 600; secret chatə yazılmasın")
    add_bullet(doc, "İnternet uplink go-live smoke testində kəsik olmalıdır")

    # ---- 15 ----
    add_heading(doc, "15. İş bölgüsü", 1)
    add_table(
        doc,
        ["Rol", "İş", "Acceptance"],
        [
            [
                "NetAdmin",
                "IP/DNS, firewall, AxTrax 1433, NTP; İnternet uplink YOX",
                "LAN URL + SQL port OK; offline sınaq",
            ],
            [
                "SysAdmin",
                "AlmaLinux, offline RPM, Postgres, Nginx, systemd, backup cron",
                "systemctl active; reboot sonrası qalxır",
            ],
            [
                "ERP ops",
                ".env, migrate, invite, axtrax_sync_status, smoke",
                "Portal/ERP/Security + event gəlir",
            ],
            [
                "Build maşın ops",
                "wheelhouse + RPM USB hazırlığı",
                "Prod-da pip/dnf offline uğurlu",
            ],
        ],
    )

    # ---- 16 ----
    add_heading(doc, "16. Xronoloji plan", 1)
    add_table(
        doc,
        ["Mərhələ", "Müddət", "İş"],
        [
            ["A. Build paket", "1–3 gün", "RPM + wheelhouse + app zip (İnternet olan maşın)"],
            ["B. OS + offline RPM", "1 gün", "AlmaLinux, lokal repo, firewall, chrony"],
            ["C. Postgres + app", "1 gün", "DB rollar, venv, migrate, .env"],
            ["D. systemd + Nginx", "0.5 gün", "web + axtrax + proxy"],
            ["E. AxTrax + backup", "0.5–1 gün", "1433, poller, cron, restore drill"],
            ["F. Pilot smoke", "1–3 gün", "invite, ticket, qonaq, Excel, offline uplink"],
            ["G. Qəbul", "1 gün", "Checklist + imza"],
        ],
    )

    # ---- 17 ----
    add_heading(doc, "17. Go-live checklist", 1)
    add_bullet(doc, "[ ] Prod serverdə İnternet uplink YOx / kəsik sınağı keçib")
    add_bullet(doc, "[ ] Docker istifadə olunmur (və ya söndürülüb) — native systemd işləyir")
    add_bullet(doc, "[ ] pip yalnız --no-index wheelhouse ilə quraşdırılıb")
    add_bullet(doc, "[ ] dnf yalnız file:// offline repo")
    add_bullet(doc, "[ ] CP_ENV=production, CP_OFFLINE=1, SEED_DEMO=0, DEBUG=0")
    add_bullet(doc, "[ ] POSTGRES_HOST=127.0.0.1; 5432 xarici bağlı")
    add_bullet(doc, "[ ] citypoint-web + citypoint-axtrax enabled")
    add_bullet(doc, "[ ] Nginx və ya :8000 LAN-dan açılır; CDN xətası yox")
    add_bullet(doc, "[ ] Admin / Reception / Security / Resident login")
    add_bullet(doc, "[ ] Ticket, qonaq, Access Excel export")
    add_bullet(doc, "[ ] AxTrax event gəlir")
    add_bullet(doc, "[ ] Invite link (SMTP və ya mail_outbox)")
    add_bullet(doc, "[ ] Backup + restore drill sənədləşdirilib")
    add_bullet(doc, "[ ] Reboot sonrası xidmətlər avtomatik qalxır")

    # ---- 18 ----
    add_heading(doc, "18. Troubleshooting", 1)
    add_table(
        doc,
        ["Problem", "Səbəb", "Həll"],
        [
            ["pip İnternetə çıxır / fail", " --no-index unudulub və ya wheel çatışmır", "wheelhouse tamamla"],
            ["dnf heç nə tapmır", "offline repo yanlış path", "baseurl=file:///opt/offline/rpms"],
            ["pymssql import error", "freetds/libsybdb yox", "RPM əlavə et, ldd yoxla"],
            ["DB connection refused", "Postgres down / host=db", "127.0.0.1; systemctl start postgresql"],
            ["CSRF 403", "CSRF_TRUSTED_ORIGINS", "URL sxemi və hostname"],
            ["AxTrax boş", "1433 / password / poller down", "nc, .env, systemctl status axtrax"],
            ["Static 404", "collectstatic / nginx alias", "yenidən collectstatic"],
            ["Permission denied", "owner citypoint deyil", "chown -R citypoint"],
        ],
    )

    # ---- 19 ----
    add_heading(doc, "19. Docker guide ilə fərq", 1)
    add_table(
        doc,
        ["Mövzu", "Docker guide", "Bu sənəd (native offline)"],
        [
            ["Konteyner", "Docker Compose", "Yox — OS prosesləri"],
            ["İnternet riski", "image pull / save-load", "RPM + wheel USB; Hub lazım deyil"],
            ["DB host", "POSTGRES_HOST=db", "POSTGRES_HOST=127.0.0.1"],
            ["Web start", "entrypoint + gunicorn", "systemd citypoint-web"],
            ["AxTrax", "AXTRAX_POLL_ON_START=1", "ayrı citypoint-axtrax.service"],
            ["Yeniləmə", "docker load", "zip + wheelhouse + restart"],
        ],
    )

    # ---- 20 ----
    add_heading(doc, "20. Əlaqəli sənədlər", 1)
    add_bullet(doc, "docs/deployment/CityPoint_AlmaLinux10_Native_Offline_Rehberi.docx (bu fayl)")
    add_bullet(doc, "docs/deployment/air-gapped-lan.md — LAN qaydaları")
    add_bullet(doc, "docs/deployment/CityPoint_AlmaLinux10_Deploy_Rehberi.docx — Docker variant (alternativ)")
    add_bullet(doc, "docs/security/postgres-roles.md")
    add_bullet(doc, "docs/backup/phase1-backup-restore.md")
    add_bullet(doc, "docs/integrations/axtrax-poller-runbook.md")
    add_bullet(doc, "bin/prod/.env.example — sahə siyahısı (POSTGRES_HOST-u 127.0.0.1 edin)")

    add_heading(doc, "21. Qəbul imza", 1)
    add_table(
        doc,
        ["Rol", "Ad", "Tarix", "İmza"],
        [
            ["NetAdmin (İnternet yox təsdiqi)", "", "", ""],
            ["SysAdmin (native + offline RPM)", "", "", ""],
            ["Build maşın (wheelhouse)", "", "", ""],
            ["ERP ops", "", "", ""],
            ["Rəhbərlik", "", "", ""],
        ],
    )

    add_heading(doc, "22. Nəticə", 1)
    add_para(
        doc,
        "City Point prod serverində İnternet olmayacağı üçün sistem Docker-suz, "
        "AlmaLinux native stack ilə quraşdırılmalıdır: offline RPM + Python wheelhouse + "
        "systemd (Gunicorn + AxTrax) + PostgreSQL localhost + LAN brauzerlər. "
        "İnternet yalnız ayrı build maşınında paket hazırlığı üçündür; "
        "go-live və istismar tam air-gapped qalır.",
    )

    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = footer.add_run("— City Point ERP · Daxili · Confidential · No-Internet / No-Docker —")
    set_run_font(r, size=9, color=RGBColor(0x64, 0x74, 0x8B))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
