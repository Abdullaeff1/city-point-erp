# Workflow A — Canlı QONAQ qəbul vərəqi

**Status:** hazırlıq COMPLETE · **canlı nəticə:** PENDING (sahə komandası doldurur)  
**Mənbə:** Reception→Security (blueprint §6, ID **A**)  
**Mühit:** yalnız təyin olunmuş test kartı; prod qonaq/vəsiqə məlumatı yox

---

## 1. QONAQ kartı və çıxış oxuyucusu

| Sahə | Dəyər |
|------|--------|
| Məsul | **NetAdmin** |
| Əməl | Təyin olunmuş test kartının AxTrax-da **QONAQ** qrupuna aid olduğunu təsdiqlə; çıxış oxuyucusunu və `bReaderOut` / istiqamətini yaz |
| Gözlənilən | Kart QONAQ-dadır; oxuyucu OUT kimi konfiqurasiya olunub |
| Sübut | AxTrax ekran şəkli / oxuyucu adı + `IdReader` + istiqamət qeydi |

**Qeyd (sahə):** _______________ · Tarix: _______________ · İmza: _______________

---

## 2. Test qonağının qəbulu

| Sahə | Dəyər |
|------|--------|
| Məsul | **Reception** |
| Əməl | Test qonağını qəbul et; kart nömrəsini **kartın üzərində çap olunduğu kimi** yaz (ön sıfırlar daxil) |
| Gözlənilən | Ziyarət `İçəridə`; ERP-də `VisitorAccess.credential` çap ilə eyni |
| Sübut | ERP jurnal sətri + kartın foto / yazılmış nömrə |

**Çap olunmuş kart:** _______________ · **ERP credential:** _______________

---

## 3. Çıxış oxuyucusu və sinxron gecikmə

| Sahə | Dəyər |
|------|--------|
| Məsul | **Security** (müşahidə) + **NetAdmin** (AxTrax hadisəsi) |
| Əməl | Kartı çıxış oxuyucusuna göstər; AxTrax hadisə vaxtını ERP `check_out_at` ilə müqayisə et |
| Gözlənilən | Ziyarət bağlanır (və ya `RETURN_PENDING` əgər vəsiqə tutulub); ERP vaxtı = hadisə vaxtı (poll vaxtı deyil) |
| Sübut | AxTrax `IdAutoEvents` / vaxt · ERP `check_out_at` · müşahidə olunan sync gecikməsi (saniyə) |

**AxTrax vaxtı:** _______________ · **ERP çıxış:** _______________ · **Gecikmə (s):** _______________

---

## 4. Elektron çıxış + açıq vəsiqə təhvili

| Sahə | Dəyər |
|------|--------|
| Məsul | **Reception** |
| Əməl | Vəsiqə tutulmuş test qonağı üçün OUT-dan sonra jurnalda «Çıxış · vəsiqə gözləyir» / `id_pending` yoxla; mövcud Reception əməli ilə fiziki qaytarmanı tamamla |
| Gözlənilən | Elektron çıxış məlum; vəsiqə flag operator tamamlayana qədər açıq qalır |
| Sübut | Əvvəl/sonra ekran vəziyyəti (status + `check_out_at`) |

**Nəticə:** _______________

---

## 5. Eyni kartın ikinci qonağa verilməsi

| Sahə | Dəyər |
|------|--------|
| Məsul | **Reception** (+ Security RO yoxlama) |
| Əməl | Eyni fiziki kartı ikinci test qonağına ver; birinci ziyarətin çıxış vaxtının dəyişmədiyini və ikinci ziyarətin müstəqil qaldığını yoxla |
| Gözlənilən | Birinci `check_out_at` saxlanır; ikinci ziyarət ayrı intervalda |
| Sübut | İki jurnal sətri (visit id, credential, giriş/çıxış) |

**Qonaq A çıxış:** _______________ · **Qonaq B status:** _______________

---

## Ambiguitet diaqnostikası (lazım olsa)

| Sahə | Dəyər |
|------|--------|
| Məsul | **Admin / IT** (Django Admin `SyncLog`) |
| Harada | `/admin/` → Integrations → Sync logs · filter `operation=guest_checkout_ambiguous` |
| Gözlənilən | `correlation_id=access_event:{id}`, `visit_ids`, kart preview; vəsiqə FIN yoxdur |
| Alternativ | ERP AxTrax health: `last_guest_checkout_ambiguous` |

---

## NetAdmin — vendor təsdiqi (kodda yoxdur)

1. Qonaq vuruşunda `iCardCode` çap badge ilə eynidirmi, yoxsa yalnız daxili koddur?  
2. Kart nömrəsi oxuyucu/controller üzrə unikaldırmı, yoxsa qlobal?  
3. QONAQ üzvlüyü yalnız AxTrax qrup konvensiyasıdırmı (ERP sorğusu yoxdur)?  
4. İki fərqli `IdAutoEvents` eyni kart + eyni `dtEventReal` ilə gələ bilərmi?
