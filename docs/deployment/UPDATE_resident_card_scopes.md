# Yeniləmə: Rezident kartı (6 bölmə) + profil gap

## 1. Migrate

```bash
cd /opt/citypoint
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart citypoint
```

Yeni miqrasiyalar:

- `residents.0015_resident_card_profile_gap` — legal_form, website, manager_position/email, bank_branch/currency, registry_extract_ref
- `leases.0003_lease_type` — `Lease.lease_type`
- `documents.0005_document_type_seed_extra` — Etibarnamə, Bank arayışı, Reyestrdən çıxarış

## 2. UI

Rezident kartı: Kart | Ümumi | Əlaqə | Bank | Sənədlər | İcarə və sahələr | Giriş

- İcarə cədvəli **oxu-only** (Lease/Space SoT)
- Billing / maliyyə profil sahələri **hələ yox** (mühasibatlıq moduluna saxlanılıb)
- Sənədlər: tip slotları + Bax (popup) + Yüklə

## 3. Billing (Scope E)

Screenshot #7 field-ləri bu paketlərə daxil deyil — gələcək mühasibatlıq scope.
