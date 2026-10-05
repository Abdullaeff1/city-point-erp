# Generate City Point AlmaLinux native offline Word guide via Word COM
$ErrorActionPreference = "Stop"
$out = Join-Path $PSScriptRoot "..\docs\deployment\CityPoint_AlmaLinux10_Native_Offline_Rehberi.docx"
$out = [System.IO.Path]::GetFullPath($out)
$dir = Split-Path $out -Parent
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
if (Test-Path $out) { Remove-Item $out -Force }

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$doc = $word.Documents.Add()

function Add-DocHeading([int]$level, [string]$text) {
  $p = $script:doc.Paragraphs.Add()
  $p.Range.Text = $text
  $p.Range.Style = "Heading $level"
}
function Add-DocPara([string]$text, [bool]$bold = $false) {
  $p = $script:doc.Paragraphs.Add()
  $p.Range.Text = $text
  $p.Range.Font.Name = "Calibri"
  $p.Range.Font.Size = 11
  $p.Range.Font.Bold = $bold
}
function Add-DocBullet([string]$text) {
  $p = $script:doc.Paragraphs.Add()
  $p.Range.Text = ("- " + $text)
  $p.Range.Font.Name = "Calibri"
  $p.Range.Font.Size = 11
}
function Add-DocCode([string]$text) {
  $p = $script:doc.Paragraphs.Add()
  $p.Range.Text = $text
  $p.Range.Font.Name = "Consolas"
  $p.Range.Font.Size = 9
}

$r = $doc.Range(0,0)
$r.Text = "CITY POINT ERP / PORTAL`r"
$r.ParagraphFormat.Alignment = 1
$r.Font.Name = "Calibri"
$r.Font.Size = 22
$r.Font.Bold = $true

Add-DocPara "AlmaLinux 10 - Docker OLMADAN - Tam offline (Internetsiz) qurasdirma rehberi" $true
$doc.Paragraphs.Last.Range.ParagraphFormat.Alignment = 1
Add-DocPara ("Versiya: 1.0  |  Tarix: " + (Get-Date -Format yyyy-MM-dd) + "  |  Native: PostgreSQL + Python venv + Gunicorn + systemd + Nginx") $false
$doc.Paragraphs.Last.Range.ParagraphFormat.Alignment = 1
$doc.Paragraphs.Last.Range.Font.Size = 9

Add-DocPara "ESAS SERT: Prod serverde INTERNET YOXDUR. Go-live ve istismar zamani dnf/pip/docker pull islemeyecek. Butun RPM, Python wheel ve kod evvelceden (Internet olan ayri masinda) hazirlanib USB/NAS ile getirilir." $true

Add-DocPara "Bu sened Docker istifadesi ETMEDEN City Point ERP/Portal-i AlmaLinux 10 uzerinde LAN/air-gapped modelde qurasdirmaq ucundur. Docker Hub asililigi Internetsiz serverde risklidir; native qurasdirma tovsiye olunan yoldur."

Add-DocHeading 1 "1. Niye Docker yox - native?"
Add-DocBullet "Serverde Internet yox -> Docker Hub-dan image cekile bilmez"
Add-DocBullet "docker save/load mumkundur, amma elave murrekkebilik ve boyuk tar fayllari"
Add-DocBullet "Native: OS RPM + pip wheelhouse - bir defe paketleyib USB ile getirirsiniz"
Add-DocBullet "systemd ile web (Gunicorn) ve AxTrax poller ayri xidmet kimi idare olunur"
Add-DocBullet "PostgreSQL AlmaLinux paketi / offline RPM - Docker volume lazim deyil"
Add-DocPara "Hedef arxitektura:" $true
Add-DocCode @'
[ Resident / Staff PC ] -> LAN -> Nginx (:80/:443) ve ya birbasa Gunicorn (:8000)
                                      |
                         Python venv + Django + Gunicorn  (systemd)
                                      |
                         PostgreSQL 16  (localhost :5432, firewall bagli)
                                      +
                         AxTrax poller  (systemd) -> AxTrax MS SQL LAN :1433
'@

Add-DocHeading 1 "2. Server resurslari"
Add-DocPara "CPU: min 4 vCPU / tovsiye 8 | RAM: min 8 GB / tovsiye 16 GB | Disk: min 100 GB SSD / tovsiye 200+ GB (DB + media + /backup + wheelhouse) | OS: AlmaLinux 10 x86_64 | Sebeke: 1 Gbit LAN, statik IP; Internet uplink YOX."

Add-DocHeading 1 "3. Iki masin modeli (mutleq)"
Add-DocPara "Prod server hec vaxt Internete qosulmur. Paketleri hazirlayan masin ayridir." $true
Add-DocBullet "Build / paket masini (Internet VAR): RPM download, pip download wheelhouse, repo zip"
Add-DocBullet "City Point prod AlmaLinux 10 (Internet YOX): USB/NAS-dan qurasdirma; yalniz LAN (brauzer + AxTrax)"
Add-DocPara "USB/NAS-da getirilen paket desti:" $true
Add-DocBullet "citypoint-app.zip - repo kodu"
Add-DocBullet "rpms/ - PostgreSQL, Python, nginx, freetds/openssl ve asililiqlar"
Add-DocBullet "wheelhouse/ - requirements.txt ucun butun .whl"
Add-DocBullet "env.template -> serverde .env (secret-ler ayri kanal)"
Add-DocBullet "Bu Word rehberi + checklist"

Add-DocHeading 1 "4. Evvelceden toplanmali melumatlar"
Add-DocBullet "Hostname / IP (erp.citypoint.local / 10.x.x.x)"
Add-DocBullet "Portal/ERP URL"
Add-DocBullet "AxTrax SQL host/port/DB + RO user/password"
Add-DocBullet "Mail: CP_OFFLINE=1 + link kopyalama (SMTP yoxdursa)"
Add-DocBullet "DJANGO_SECRET_KEY, Postgres sifreleri (cp_migrator / cp_app / cp_readonly)"
Add-DocBullet "Backup yolu, daxili NTP, firewall qaydalari"

Add-DocHeading 1 "5. Build masininda paket hazirligi (Internet VAR)"
Add-DocHeading 2 "5.1. Tetbiq kodu"
Add-DocCode @'
git clone REPO_URL city-point-system
cd city-point-system
zip -r /media/usb/citypoint-app.zip . -x "*.git*" -x "*__pycache__*" -x "media/*"
'@
Add-DocHeading 2 "5.2. Python wheelhouse (PyPI offline)"
Add-DocPara "Prod serverde pip install Internete cixmayacaq. Wheel-leri Windows-da yuklemek risklidir - AlmaLinux 10 (eyni glibc) masinda hazirlayin." $true
Add-DocCode @'
python3.12 -m venv /tmp/cp-build-venv
source /tmp/cp-build-venv/bin/activate
pip install --upgrade pip wheel
mkdir -p /media/usb/wheelhouse
pip download -r requirements.txt -d /media/usb/wheelhouse
'@
Add-DocHeading 2 "5.3. RPM paketleri"
Add-DocBullet "python3, python3-pip, python3-devel"
Add-DocBullet "postgresql-server, postgresql, postgresql-contrib"
Add-DocBullet "nginx, firewalld, chrony, unzip, tar, gzip"
Add-DocBullet "freetds / freetds-libs (pymssql ucun)"
Add-DocCode @'
sudo dnf install -y "dnf-command(download)" createrepo_c
mkdir -p /media/usb/rpms && cd /media/usb/rpms
sudo dnf download --resolve --arch=x86_64 python3 python3-pip python3-devel postgresql-server postgresql postgresql-contrib nginx firewalld chrony unzip tar gzip freetds freetds-libs
createrepo_c .
'@
Add-DocPara "Paket adlari AlmaLinux 10 repo-da ferqlene biler - dnf search ile tesdiq edin. Build ve prod eyni major OS olmalidir."

Add-DocHeading 1 "6. Prod server - OS (Internet YOX)"
Add-DocHeading 2 "6.1. AlmaLinux 10"
Add-DocBullet "ISO ile Minimal/Server (Internet teleb olunmur)"
Add-DocBullet "Statik IP, hostname, Asia/Baku; yalniz LAN"
Add-DocBullet "citypoint istifadeci + sudo"
Add-DocHeading 2 "6.2. Offline RPM"
Add-DocCode @'
sudo mkdir -p /opt/offline/rpms
sudo cp -a /mnt/usb/rpms/. /opt/offline/rpms/
sudo tee /etc/yum.repos.d/citypoint-offline.repo << "EOF"
[citypoint-offline]
name=CityPoint Offline RPMs
baseurl=file:///opt/offline/rpms
enabled=1
gpgcheck=0
EOF
sudo dnf clean all
sudo dnf --disablerepo=* --enablerepo=citypoint-offline install -y python3 python3-pip python3-devel postgresql-server postgresql postgresql-contrib nginx firewalld chrony unzip tar gzip freetds freetds-libs
'@
Add-DocHeading 2 "6.3. Vaxt ve firewall"
Add-DocCode @'
sudo systemctl enable --now chronyd
sudo systemctl enable --now firewalld
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
# 5432 hec vaxt LAN-a aciq olmamalidir
'@

Add-DocHeading 1 "7. PostgreSQL (native)"
Add-DocCode @'
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
sudo -u postgres psql << "SQL"
CREATE DATABASE citypoint;
CREATE ROLE cp_migrator LOGIN PASSWORD 'CHANGE_ME_MIGRATOR';
CREATE ROLE cp_app LOGIN PASSWORD 'CHANGE_ME_APP';
CREATE ROLE cp_readonly LOGIN PASSWORD 'CHANGE_ME_READONLY';
GRANT CONNECT ON DATABASE citypoint TO cp_migrator, cp_app, cp_readonly;
\c citypoint
GRANT USAGE ON SCHEMA public TO cp_migrator, cp_app, cp_readonly;
GRANT ALL ON SCHEMA public TO cp_migrator;
SQL
'@
Add-DocPara "pg_hba.conf: yalniz local/127.0.0.1. listen_addresses = localhost. Etrafli: docs/security/postgres-roles.md. Migrate-den sonra cp_app-e DML grant."

Add-DocHeading 1 "8. Tetbiq (venv + offline pip)"
Add-DocHeading 2 "8.1. Kod"
Add-DocCode @'
sudo mkdir -p /opt/citypoint /opt/offline/wheelhouse /backup/citypoint
sudo useradd -r -m -d /opt/citypoint -s /bin/bash citypoint || true
sudo unzip /mnt/usb/citypoint-app.zip -d /opt/citypoint
sudo cp -a /mnt/usb/wheelhouse/. /opt/offline/wheelhouse/
sudo chown -R citypoint:citypoint /opt/citypoint /backup/citypoint
'@
Add-DocHeading 2 "8.2. Virtualenv"
Add-DocCode @'
sudo -u citypoint -H bash << "EOF"
cd /opt/citypoint
python3 -m venv /opt/citypoint/.venv
source /opt/citypoint/.venv/bin/activate
pip install --no-index --find-links=/opt/offline/wheelhouse -r requirements.txt
mkdir -p media staticfiles var/mail_outbox var
EOF
'@
Add-DocPara "pip yalniz --no-index ile. Internete cehd olmamalidir - eks halde wheelhouse natamamdir." $true
Add-DocHeading 2 "8.3. .env"
Add-DocCode @'
CP_ENV=production
CP_OFFLINE=1
DJANGO_DEBUG=0
SEED_DEMO=0
POSTGRES_HOST=127.0.0.1
POSTGRES_USER=cp_app
AXTRAX_POLL_ON_START=0
# + SECRET_KEY, ALLOWED_HOSTS, CSRF, AxTrax TURNSTILE_MSSQL_*, passwords
# chmod 600
# AXTRAX_POLL_ON_START=0 cunki poller ayri systemd unit-dir
# POSTGRES_HOST=127.0.0.1 (Docker-daki db hostname YOX)
'@
Add-DocHeading 2 "8.4. Migrate / collectstatic / invite"
Add-DocCode @'
cd /opt/citypoint && source .venv/bin/activate
set -a; source bin/prod/.env; set +a
export POSTGRES_USER=cp_migrator POSTGRES_PASSWORD=CHANGE_ME_MIGRATOR
python manage.py migrate --noinput
python manage.py collectstatic --noinput
# sonra cp_app DML grant; createsuperuser; invite_portal_user
'@

Add-DocHeading 1 "9. systemd (Docker evezine)"
Add-DocHeading 2 "9.1. citypoint-web.service"
Add-DocCode @'
[Unit]
Description=City Point ERP Gunicorn
After=network.target postgresql.service
Requires=postgresql.service
[Service]
Type=simple
User=citypoint
Group=citypoint
WorkingDirectory=/opt/citypoint
EnvironmentFile=/opt/citypoint/bin/prod/.env
ExecStart=/opt/citypoint/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=always
[Install]
WantedBy=multi-user.target
'@
Add-DocHeading 2 "9.2. citypoint-axtrax.service"
Add-DocCode @'
[Unit]
Description=City Point AxTrax poller
After=network.target citypoint-web.service
[Service]
Type=simple
User=citypoint
WorkingDirectory=/opt/citypoint
EnvironmentFile=/opt/citypoint/bin/prod/.env
ExecStart=/opt/citypoint/.venv/bin/python manage.py poll_axtrax
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
'@
Add-DocCode "sudo systemctl daemon-reload && sudo systemctl enable --now citypoint-web citypoint-axtrax"
Add-DocPara "Windows Scheduled Task lazim deyil. Internet teleb olunmur."

Add-DocHeading 1 "10. Nginx (tovsiye)"
Add-DocCode @'
server {
    listen 80;
    server_name erp.citypoint.local;
    client_max_body_size 50M;
    location /static/ { alias /opt/citypoint/staticfiles/; }
    location /media/  { alias /opt/citypoint/media/; }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
'@
Add-DocPara "Lets Encrypt air-gap-de yoxdur - daxili CA istifade edin."

Add-DocHeading 1 "11. AxTrax - offline LAN"
Add-DocBullet "nc -vz AXTRAX_IP 1433"
Add-DocBullet "TURNSTILE_MSSQL_* yalniz .env-de"
Add-DocBullet "axtrax_sync_status; lazimsa backfill_axtrax_events --from=YYYY-MM-DD"
Add-DocBullet "Cloud sync yox - yalniz LAN RO SQL"

Add-DocHeading 1 "12. Backup / restore"
Add-DocCode @'
# cron: pg_dump | gzip -> /backup/citypoint/db-YYYYMMDD.sql.gz
# media tar -> /backup/citypoint/media-YYYYMMDD.tar.gz
# .pgpass chmod 600; restore drill mutleq
'@
Add-DocPara "Backup etibarli deyil, eger restore sinagi yoxdursa." $true

Add-DocHeading 1 "13. Yenileme (Internetsiz)"
Add-DocBullet "Build: yeni zip + lazim olsa wheelhouse -> USB"
Add-DocBullet "Prod: backup -> kod -> pip --no-index -> migrate -> collectstatic -> systemctl restart"
Add-DocBullet "Rollback: kohne zip + DB dump"

Add-DocHeading 1 "14. Tehlukesizlik"
Add-DocBullet "SEED_DEMO=0, DEBUG=0, CDN yox"
Add-DocBullet "Runtime-da pip/dnf Internete cixmir"
Add-DocBullet "Postgres yalniz localhost; .env chmod 600"
Add-DocBullet "Go-live smoke: Internet uplink kesik"

Add-DocHeading 1 "15. Is bolgusu"
Add-DocBullet "NetAdmin: IP/DNS/firewall/AxTrax/NTP; Internet uplink YOX"
Add-DocBullet "SysAdmin: AlmaLinux, offline RPM, Postgres, Nginx, systemd, backup"
Add-DocBullet "Build ops: wheelhouse + RPM USB"
Add-DocBullet "ERP ops: .env, migrate, invite, smoke"

Add-DocHeading 1 "16. Xronoloji plan"
Add-DocBullet "A. Build paket 1-3 gun | B. OS+RPM 1 gun | C. Postgres+app 1 gun"
Add-DocBullet "D. systemd+Nginx 0.5 | E. AxTrax+backup 0.5-1 | F. Pilot 1-3 | G. Qebul 1"

Add-DocHeading 1 "17. Go-live checklist"
Add-DocBullet "[ ] Prod-da Internet uplink YOX / kesik sinagi kecib"
Add-DocBullet "[ ] Docker istifade olunmur - native systemd"
Add-DocBullet "[ ] pip yalniz --no-index; dnf yalniz file:// offline repo"
Add-DocBullet "[ ] CP_ENV=production, CP_OFFLINE=1, SEED_DEMO=0, DEBUG=0"
Add-DocBullet "[ ] POSTGRES_HOST=127.0.0.1; 5432 xarici bagli"
Add-DocBullet "[ ] citypoint-web + citypoint-axtrax enabled"
Add-DocBullet "[ ] LAN-dan portal/ERP; CDN xetasi yox"
Add-DocBullet "[ ] Admin/Reception/Security/Resident + ticket/qonaq/Excel"
Add-DocBullet "[ ] AxTrax event; invite link; backup+restore drill; reboot OK"

Add-DocHeading 1 "18. Troubleshooting"
Add-DocBullet "pip fail -> wheelhouse tamamla (--no-index)"
Add-DocBullet "dnf tapmir -> baseurl=file:///opt/offline/rpms"
Add-DocBullet "pymssql error -> freetds RPM"
Add-DocBullet "DB refused -> 127.0.0.1, postgresql start (host=db YOX)"
Add-DocBullet "CSRF 403 -> CSRF_TRUSTED_ORIGINS"
Add-DocBullet "AxTrax bos -> 1433, password, poller status"
Add-DocBullet "Static 404 -> collectstatic / nginx alias"

Add-DocHeading 1 "19. Docker guide ile ferq"
Add-DocBullet "Docker: Compose + POSTGRES_HOST=db + image save/load"
Add-DocBullet "Bu sened: systemd + POSTGRES_HOST=127.0.0.1 + RPM/wheel USB; Hub lazim deyil"
Add-DocBullet "AxTrax: Docker-da AXTRAX_POLL_ON_START=1; burada ayri citypoint-axtrax.service"

Add-DocHeading 1 "20. Elaqeli senedler"
Add-DocBullet "docs/deployment/air-gapped-lan.md"
Add-DocBullet "CityPoint_AlmaLinux10_Deploy_Rehberi.docx - Docker alternativ"
Add-DocBullet "docs/security/postgres-roles.md, docs/backup/phase1-backup-restore.md"
Add-DocBullet "docs/integrations/axtrax-poller-runbook.md, bin/prod/.env.example"

Add-DocHeading 1 "21. Qebul imza"
Add-DocPara "NetAdmin (Internet yox) ____  SysAdmin (native) ____  Build (wheelhouse) ____  ERP ops ____  Rehberlik ____"

Add-DocHeading 1 "22. Netice"
Add-DocPara "City Point prod serverinde Internet olmayacagi ucun sistem Docker-suz qurasdirilmalidir: offline RPM + Python wheelhouse + systemd (Gunicorn + AxTrax) + PostgreSQL localhost + LAN brauzerler. Internet yalniz ayri build masininda paket hazirligi ucundur; go-live ve istismar tam air-gapped qalir."

Add-DocPara "- City Point ERP | Daxili | Confidential | No-Internet / No-Docker -" $false
$doc.Paragraphs.Last.Range.ParagraphFormat.Alignment = 1
$doc.Paragraphs.Last.Range.Font.Size = 9

$wdFormatXMLDocument = 12
$doc.SaveAs2($out, $wdFormatXMLDocument)
$doc.Close()
$word.Quit()
[System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
Write-Output "Wrote $out"
Get-Item $out | Format-List FullName, Length, LastWriteTime

