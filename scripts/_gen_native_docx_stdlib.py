# -*- coding: utf-8 -*-
# Minimal OOXML docx writer (no external deps)
import zipfile, textwrap
from pathlib import Path
from datetime import date
from xml.sax.saxutils import escape

OUT = Path(r'docs/deployment/CityPoint_AlmaLinux10_Native_Offline_Rehberi.docx')

def p(text, style='Normal', bold=False, size=22, font='Calibri', align=None):
    # size in half-points
    jc = f'<w:jc w:val="{align}"/>' if align else ''
    b = '<w:b/>' if bold else ''
    lines = escape(text).split('\n')
    runs = []
    for i, line in enumerate(lines):
        if i:
            runs.append('<w:r><w:br/></w:r>')
        runs.append(f'<w:r><w:rPr>{b}<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr><w:t xml:space="preserve">{line}</w:t></w:r>')
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{jc}</w:pPr>{"".join(runs)}</w:p>'

def h(level, text):
    return p(text, style=f'Heading{level}', bold=True, size=32 if level==1 else 26)

def bullet(text):
    # simple dash para (avoid numbering deps)
    return p('• ' + text, size=22)

def code(text):
    return p(text, size=18, font='Consolas')

parts = []
parts.append(p('CITY POINT ERP / PORTAL', bold=True, size=44, align='center'))
parts.append(p('AlmaLinux 10 — Docker OLMADAN · Tam offline (İnternetsiz) quraşdırma rəhbəri', bold=True, size=26, align='center'))
parts.append(p(f'Versiya: 1.0  ·  Tarix: {date.today().isoformat()}  ·  Native: PostgreSQL + Python venv + Gunicorn + systemd + Nginx', size=18, align='center'))
parts.append(p('ƏSAS ŞƏRT: Prod serverdə İNTERNET YOXDUR. Go-live və istismar zamanı dnf/pip/docker pull işləməyəcək. Bütün RPM, Python wheel və kod əvvəlcədən (İnternet olan ayrı maşında) hazırlanıb USB/NAS ilə gətirilir.', bold=True, size=22))
parts.append(p('Bu sənəd Docker istifadəsi ETMƏDƏN City Point ERP/Portal-ı AlmaLinux 10 üzərində LAN/air-gapped modeldə quraşdırmaq üçündür. Docker Hub asılılığı İnternetsiz serverdə risklidir; native quraşdırma tövsiyə olunan yoldur.'))

parts.append(h(1, '1. Niyə Docker yox — native?'))
for t in [
 'Serverdə İnternet yox → Docker Hub-dan image çəkilə bilməz',
 'docker save/load mümkündür, amma əlavə mürəkkəblik və böyük tar faylları',
 'Native: OS RPM + pip wheelhouse — bir dəfə paketləyib USB ilə gətirirsiniz',
 'systemd ilə web (Gunicorn) və AxTrax poller ayrı xidmət kimi idarə olunur',
 'PostgreSQL AlmaLinux paketi / offline RPM — Docker volume lazım deyil']:
    parts.append(bullet(t))
parts.append(p('Hədəf arxitektura:', bold=True))
parts.append(code('[ Resident / Staff PC ] → LAN → Nginx (:80/:443) və ya birbaşa Gunicorn (:8000)\n                                      ↓\n                         Python venv + Django + Gunicorn  (systemd)\n                                      ↓\n                         PostgreSQL (localhost :5432, firewall bağlı)\n                                      +\n                         AxTrax poller (systemd) → AxTrax MS SQL LAN :1433'))

parts.append(h(1, '2. Server resursları'))
parts.append(p('CPU: min 4 vCPU / tövsiyə 8 · RAM: min 8 GB / tövsiyə 16 GB · Disk: min 100 GB SSD / tövsiyə 200+ GB (DB + media + /backup + wheelhouse) · OS: AlmaLinux 10 x86_64 · Şəbəkə: 1 Gbit LAN, statik IP; İnternet uplink YOX.'))

parts.append(h(1, '3. İki maşın modeli (mütləq)'))
parts.append(p('Prod server heç vaxt İnternetə qoşulmur. Paketləri hazırlayan maşın ayrıdır.', bold=True))
parts.append(bullet('Build / paket maşını (İnternet VAR): RPM download, pip download wheelhouse, repo zip'))
parts.append(bullet('City Point prod AlmaLinux 10 (İnternet YOX): USB/NAS-dan quraşdırma; yalnız LAN (brauzer + AxTrax)'))
parts.append(p('USB/NAS-da gətirilən paket dəsti:', bold=True))
for t in ['citypoint-app.zip — repo kodu','rpms/ — PostgreSQL, Python, nginx, freetds və asılılıqlar','wheelhouse/ — requirements.txt üçün bütün .whl','env.template → serverdə .env (secret-lər ayrı kanal)','Bu Word rəhbəri + checklist']:
    parts.append(bullet(t))

parts.append(h(1, '4. Əvvəlcədən toplanmalı məlumatlar'))
for t in ['Hostname / IP (erp.citypoint.local / 10.x.x.x)','Portal/ERP URL','AxTrax SQL host/port/DB + RO user/password','Mail: CP_OFFLINE=1 + link kopyalama (SMTP yoxdursa)','DJANGO_SECRET_KEY, Postgres şifrələri (cp_migrator / cp_app / cp_readonly)','Backup yolu, daxili NTP, firewall qaydaları']:
    parts.append(bullet(t))

parts.append(h(1, '5. Build maşınında paket hazırlığı (İnternet VAR)'))
parts.append(h(2, '5.1. Tətbiq kodu'))
parts.append(code('git clone <repo> city-point-system\ncd city-point-system\nzip -r /media/usb/citypoint-app.zip . -x \'*.git*\' -x \'*__pycache__*\' -x \'media/*\''))
parts.append(h(2, '5.2. Python wheelhouse (PyPI offline)'))
parts.append(p('Prod serverdə pip install İnternetə çıxmayacaq. Wheel-ləri Windows-da yükləmək risklidir — AlmaLinux 10 (eyni glibc) maşında hazırlayın.', bold=True))
parts.append(code('python3.12 -m venv /tmp/cp-build-venv\nsource /tmp/cp-build-venv/bin/activate\npip install --upgrade pip wheel\nmkdir -p /media/usb/wheelhouse\npip download -r requirements.txt -d /media/usb/wheelhouse'))
parts.append(h(2, '5.3. RPM paketləri'))
for t in ['python3, python3-pip, python3-devel','postgresql-server, postgresql, postgresql-contrib','nginx, firewalld, chrony, unzip, tar, gzip','freetds / freetds-libs (pymssql üçün)']:
    parts.append(bullet(t))
parts.append(code('sudo dnf install -y \'dnf-command(download)\' createrepo_c\nmkdir -p /media/usb/rpms && cd /media/usb/rpms\nsudo dnf download --resolve --arch=x86_64 python3 python3-pip python3-devel postgresql-server postgresql postgresql-contrib nginx firewalld chrony unzip tar gzip freetds freetds-libs\ncreaterepo_c .'))
parts.append(p('Paket adları AlmaLinux 10 repo-da fərqlənə bilər — dnf search ilə təsdiq edin. Build və prod eyni major OS olmalıdır.'))

parts.append(h(1, '6. Prod server — OS (İnternet YOX)'))
parts.append(h(2, '6.1. AlmaLinux 10'))
for t in ['ISO ilə Minimal/Server (İnternet tələb olunmur)','Statik IP, hostname, Asia/Baku; yalnız LAN','citypoint istifadəçisi + sudo']:
    parts.append(bullet(t))
parts.append(h(2, '6.2. Offline RPM'))
parts.append(code('sudo mkdir -p /opt/offline/rpms\nsudo cp -a /mnt/usb/rpms/. /opt/offline/rpms/\nsudo tee /etc/yum.repos.d/citypoint-offline.repo <<\'EOF\'\n[citypoint-offline]\nname=CityPoint Offline RPMs\nbaseurl=file:///opt/offline/rpms\nenabled=1\ngpgcheck=0\nEOF\nsudo dnf clean all\nsudo dnf --disablerepo=\'*\' --enablerepo=citypoint-offline install -y python3 python3-pip python3-devel postgresql-server postgresql postgresql-contrib nginx firewalld chrony unzip tar gzip freetds freetds-libs'))
parts.append(h(2, '6.3. Vaxt və firewall'))
parts.append(code('sudo systemctl enable --now chronyd\nsudo systemctl enable --now firewalld\nsudo firewall-cmd --permanent --add-service=http\nsudo firewall-cmd --permanent --add-service=https\nsudo firewall-cmd --reload\n# 5432 heç vaxt LAN-a açıq olmamalıdır'))

parts.append(h(1, '7. PostgreSQL (native)'))
parts.append(code('sudo postgresql-setup --initdb\nsudo systemctl enable --now postgresql\nsudo -u postgres psql <<\'SQL\'\nCREATE DATABASE citypoint;\nCREATE ROLE cp_migrator LOGIN PASSWORD \'CHANGE_ME_MIGRATOR\';\nCREATE ROLE cp_app LOGIN PASSWORD \'CHANGE_ME_APP\';\nCREATE ROLE cp_readonly LOGIN PASSWORD \'CHANGE_ME_READONLY\';\nGRANT CONNECT ON DATABASE citypoint TO cp_migrator, cp_app, cp_readonly;\n\\\\c citypoint\nGRANT USAGE ON SCHEMA public TO cp_migrator, cp_app, cp_readonly;\nGRANT ALL ON SCHEMA public TO cp_migrator;\nSQL'))
parts.append(p('pg_hba.conf: yalnız local/127.0.0.1. listen_addresses = localhost. Ətraflı: docs/security/postgres-roles.md. Migrate-dən sonra cp_app-ə DML grant.'))

parts.append(h(1, '8. Tətbiq (venv + offline pip)'))
parts.append(h(2, '8.1. Kod'))
parts.append(code('sudo mkdir -p /opt/citypoint /opt/offline/wheelhouse /backup/citypoint\nsudo useradd -r -m -d /opt/citypoint -s /bin/bash citypoint || true\nsudo unzip /mnt/usb/citypoint-app.zip -d /opt/citypoint\nsudo cp -a /mnt/usb/wheelhouse/. /opt/offline/wheelhouse/\nsudo chown -R citypoint:citypoint /opt/citypoint /backup/citypoint'))
parts.append(h(2, '8.2. Virtualenv'))
parts.append(code('sudo -u citypoint -H bash <<\'EOF\'\ncd /opt/citypoint\npython3 -m venv /opt/citypoint/.venv\nsource /opt/citypoint/.venv/bin/activate\npip install --no-index --find-links=/opt/offline/wheelhouse -r requirements.txt\nmkdir -p media staticfiles var/mail_outbox var\nEOF'))
parts.append(p('pip yalnız --no-index ilə. İnternetə cəhd olmamalıdır — əks halda wheelhouse natamamdır.', bold=True))
parts.append(h(2, '8.3. .env'))
parts.append(code('CP_ENV=production\nCP_OFFLINE=1\nDJANGO_DEBUG=0\nSEED_DEMO=0\nPOSTGRES_HOST=127.0.0.1\nPOSTGRES_USER=cp_app\nAXTRAX_POLL_ON_START=0\n# + SECRET_KEY, ALLOWED_HOSTS, CSRF, AxTrax TURNSTILE_MSSQL_*, passwords\n# chmod 600\n# AXTRAX_POLL_ON_START=0 çünki poller ayrı systemd unit-dir\n# POSTGRES_HOST=127.0.0.1 (Docker-dakı db hostname YOX)'))
parts.append(h(2, '8.4. Migrate / collectstatic / invite'))
parts.append(code('cd /opt/citypoint && source .venv/bin/activate\nset -a; source bin/prod/.env; set +a\nexport POSTGRES_USER=cp_migrator POSTGRES_PASSWORD=CHANGE_ME_MIGRATOR\npython manage.py migrate --noinput\npython manage.py collectstatic --noinput\n# sonra cp_app DML grant; createsuperuser; invite_portal_user'))

parts.append(h(1, '9. systemd (Docker əvəzinə)'))
parts.append(h(2, '9.1. citypoint-web.service'))
parts.append(code('[Unit]\nDescription=City Point ERP Gunicorn\nAfter=network.target postgresql.service\nRequires=postgresql.service\n[Service]\nType=simple\nUser=citypoint\nGroup=citypoint\nWorkingDirectory=/opt/citypoint\nEnvironmentFile=/opt/citypoint/bin/prod/.env\nExecStart=/opt/citypoint/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120\nRestart=always\n[Install]\nWantedBy=multi-user.target'))
parts.append(h(2, '9.2. citypoint-axtrax.service'))
parts.append(code('[Unit]\nDescription=City Point AxTrax poller\nAfter=network.target citypoint-web.service\n[Service]\nType=simple\nUser=citypoint\nWorkingDirectory=/opt/citypoint\nEnvironmentFile=/opt/citypoint/bin/prod/.env\nExecStart=/opt/citypoint/.venv/bin/python manage.py poll_axtrax\nRestart=always\nRestartSec=10\n[Install]\nWantedBy=multi-user.target'))
parts.append(code('sudo systemctl daemon-reload && sudo systemctl enable --now citypoint-web citypoint-axtrax'))
parts.append(p('Windows Scheduled Task lazım deyil. İnternet tələb olunmur.'))

parts.append(h(1, '10. Nginx (tövsiyə)'))
parts.append(code('server {\n    listen 80;\n    server_name erp.citypoint.local;\n    client_max_body_size 50M;\n    location /static/ { alias /opt/citypoint/staticfiles/; }\n    location /media/  { alias /opt/citypoint/media/; }\n    location / {\n        proxy_pass http://127.0.0.1:8000;\n        proxy_set_header Host System.Management.Automation.Internal.Host.InternalHost;\n        proxy_set_header X-Forwarded-For ;\n    }\n}'))
parts.append(p('Let\'s Encrypt air-gap-də yoxdur — daxili CA istifadə edin.'))

parts.append(h(1, '11. AxTrax — offline LAN'))
for t in ['nc -vz AXTRAX_IP 1433','TURNSTILE_MSSQL_* yalnız .env-də','axtrax_sync_status; lazımsa backfill_axtrax_events --from=YYYY-MM-DD','Cloud sync yox — yalnız LAN RO SQL']:
    parts.append(bullet(t))

parts.append(h(1, '12. Backup / restore'))
parts.append(code('# cron: pg_dump | gzip → /backup/citypoint/db-YYYYMMDD.sql.gz\n# media tar → /backup/citypoint/media-YYYYMMDD.tar.gz\n# .pgpass chmod 600; restore drill mütləq'))
parts.append(p('Backup etibarlı deyil, əgər restore sınağı yoxdursa.', bold=True))

parts.append(h(1, '13. Yeniləmə (İnternetsiz)'))
for t in ['Build: yeni zip + lazım olsa wheelhouse → USB','Prod: backup → kod → pip --no-index → migrate → collectstatic → systemctl restart','Rollback: köhnə zip + DB dump']:
    parts.append(bullet(t))

parts.append(h(1, '14. Təhlükəsizlik'))
for t in ['SEED_DEMO=0, DEBUG=0, CDN yox','Runtime-da pip/dnf İnternetə çıxmır','Postgres yalnız localhost; .env chmod 600','Go-live smoke: İnternet uplink kəsik']:
    parts.append(bullet(t))

parts.append(h(1, '15. İş bölgüsü'))
for t in ['NetAdmin: IP/DNS/firewall/AxTrax/NTP; İnternet uplink YOX','SysAdmin: AlmaLinux, offline RPM, Postgres, Nginx, systemd, backup','Build ops: wheelhouse + RPM USB','ERP ops: .env, migrate, invite, smoke']:
    parts.append(bullet(t))

parts.append(h(1, '16. Xronoloji plan'))
parts.append(bullet('A. Build paket 1–3 gün · B. OS+RPM 1 gün · C. Postgres+app 1 gün'))
parts.append(bullet('D. systemd+Nginx 0.5 · E. AxTrax+backup 0.5–1 · F. Pilot 1–3 · G. Qəbul 1'))

parts.append(h(1, '17. Go-live checklist'))
for t in ['[ ] Prod-da İnternet uplink YOX / kəsik sınağı keçib','[ ] Docker istifadə olunmur — native systemd','[ ] pip yalnız --no-index; dnf yalnız file:// offline repo','[ ] CP_ENV=production, CP_OFFLINE=1, SEED_DEMO=0, DEBUG=0','[ ] POSTGRES_HOST=127.0.0.1; 5432 xarici bağlı','[ ] citypoint-web + citypoint-axtrax enabled','[ ] LAN-dan portal/ERP; CDN xətası yox','[ ] Admin/Reception/Security/Resident + ticket/qonaq/Excel','[ ] AxTrax event; invite link; backup+restore drill; reboot OK']:
    parts.append(bullet(t))

parts.append(h(1, '18. Troubleshooting'))
for t in ['pip fail → wheelhouse tamamla (--no-index)','dnf tapmır → baseurl=file:///opt/offline/rpms','pymssql error → freetds RPM','DB refused → 127.0.0.1, postgresql start (host=db YOX)','CSRF 403 → CSRF_TRUSTED_ORIGINS','AxTrax boş → 1433, password, poller status','Static 404 → collectstatic / nginx alias']:
    parts.append(bullet(t))

parts.append(h(1, '19. Docker guide ilə fərq'))
parts.append(bullet('Docker: Compose + POSTGRES_HOST=db + image save/load'))
parts.append(bullet('Bu sənəd: systemd + POSTGRES_HOST=127.0.0.1 + RPM/wheel USB; Hub lazım deyil'))
parts.append(bullet('AxTrax: Docker-da AXTRAX_POLL_ON_START=1; burada ayrı citypoint-axtrax.service'))

parts.append(h(1, '20. Əlaqəli sənədlər'))
for t in ['docs/deployment/air-gapped-lan.md','CityPoint_AlmaLinux10_Deploy_Rehberi.docx — Docker alternativ','docs/security/postgres-roles.md, docs/backup/phase1-backup-restore.md','docs/integrations/axtrax-poller-runbook.md, bin/prod/.env.example']:
    parts.append(bullet(t))

parts.append(h(1, '21. Qəbul imza'))
parts.append(p('NetAdmin (İnternet yox) ____   SysAdmin (native) ____   Build (wheelhouse) ____   ERP ops ____   Rəhbərlik ____'))

parts.append(h(1, '22. Nəticə'))
parts.append(p('City Point prod serverində İnternet olmayacağı üçün sistem Docker-suz quraşdırılmalıdır: offline RPM + Python wheelhouse + systemd (Gunicorn + AxTrax) + PostgreSQL localhost + LAN brauzerlər. İnternet yalnız ayrı build maşınında paket hazırlığı üçündür; go-live və istismar tam air-gapped qalır.'))
parts.append(p('— City Point ERP · Daxili · Confidential · No-Internet / No-Docker —', size=18, align='center'))

body = ''.join(parts)
document_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body}
    <w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>
  </w:body>
</w:document>'''

content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>'''

rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''

word_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/><w:qFormat/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:spacing w:before="240" w:after="120"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/><w:color w:val="1F497D"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:spacing w:before="200" w:after="100"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:color w:val="1F497D"/></w:rPr></w:style>
</w:styles>'''

OUT.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUT, 'w', compression=zipfile.ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml', content_types)
    z.writestr('_rels/.rels', rels)
    z.writestr('word/document.xml', document_xml)
    z.writestr('word/_rels/document.xml.rels', word_rels)
    z.writestr('word/styles.xml', styles)
print('Wrote', OUT, 'bytes', OUT.stat().st_size)
