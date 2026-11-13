# Seed / import data

Bu qovluq gitdədir — `git pull` sonrası eyni mənbədən sahələri yükləmək üçündür.

## Sahələr (Building / Floor / Space)

```bash
# Docker
docker compose -f bin/dev/docker-compose.yml exec web python manage.py loaddata docs/data/property_spaces.json

# və ya Excel import (mərtəbə + sahə + şirkət uyğunlaşdırma)
docker compose -f bin/dev/docker-compose.yml exec web python manage.py import_lease_spaces --file docs/data/cp_icare_ve_bos_saheler.xlsx
```

`seed_demo` boş DB-də fixture-i avtomatik yükləyir (əgər Space yoxdursa).

## Nə gitdə yoxdur

- `.env`, loglar, `var/private_media`, böyük NetAdmin zip-ləri — secret / lokal runtime.
- Postgres DB özü — yalnız fixture/import ilə bərpa olunur.
