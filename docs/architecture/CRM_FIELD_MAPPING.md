# CRM — Excel / form → canonical mapping (A.10 T0)

## Excel sütunları → Lead / Opportunity

| Excel | CRM sahə | Tip |
|-------|----------|-----|
| Şirkət adı | `Lead.company_name` | Char |
| Əlaqəli şəxs | `Lead.full_name` | Char |
| Əlaqə Nöm | `Lead.phone` | Char |
| Müraciət Tarixi | `Lead.inquired_at` | Date |
| Lid mənbəyi | `Lead.source` (+ `source_note`) | Choice |
| Tələb olunan sahə | `min_area_m2` / `max_area_m2` (+ `initial_note`) | Decimal |
| Seçim edilən sahə | Offer/Opportunity → `Space` FK | FK |
| Qiymət | OfferVersion snapshot | Decimal |
| Lid statusu | `pipeline_stage` / activity | Choice |
| Nəticə | `outcome` + `outcome_note` | Choice |
| Sorğu statusu | `record_status` | Choice |
| Qeydlər | `LeadActivity` | Timeline |

## Mənbə alias → canonical

| Excel / dil | Kod |
|-------------|-----|
| Website | `website` |
| Telefon / Phone | `phone` |
| E-mail / Email Marketing | `email_marketing` və ya `email` |
| Walk-in | `walk_in` |
| Yönləndirmə / Referral | `referral` |
| Targeting reklamı | `targeting` |
| Soyuq zənglər | `cold_call` |
| Sosial Şəbəkə / SMM / Instagram | `social_media` |
| Bilboard | `billboard` |
| Birbaşa müraciət / Birbaşa görüşlər | `direct` |
| Manual | `manual` |
| Digər / naməlum | `other` + `source_note` |

## Status xəritəsi

### Qualification
| Məna | Kod |
|------|-----|
| Qiymətləndirilməyib | `unreviewed` |
| Potensial | `potential` |
| Qeyri-potensial | `non_potential` |

### Pipeline stage (Excel → kod)
| Excel | Kod |
|-------|-----|
| Yeni sorğu / İşlənilir | `working` |
| Cavab gözlənilir | `contact_pending` |
| Görüş təyin olunub | `meeting_scheduled` |
| Sahəyə baxış (plan) | `viewing_scheduled` |
| Sahəyə baxış keçirilib | `viewing_completed` |
| Danışıqlar mərhələsində | `negotiation` |
| Təklif göndərilib | `offer_sent` |
| Müqavilə mərhələsində | `lease_stage` |
| Əməkdaşlıq / qazanıldı | `won` |
| İtirildi / bağlandı (uduzma) | `lost` |
| Gözləntidə | `on_hold` |

### record_status
| Excel | Kod |
|-------|-----|
| Açıqdır | `open` |
| Gözləntidə | `waiting` |
| Bağlıdır | `closed` |

### outcome
| Excel / məna | Kod |
|--------------|-----|
| Əməkdaşlıq təmin olunub | `cooperation_secured` |
| Təklif qəbul olunmayıb | `offer_rejected` |
| Müştəri geri dönüş etməyib | `no_response` |
| Maraqlı deyil / köçüblər | `not_interested` |
| Yanlış sorğu | `invalid_request` |
| Digər | `other` |

## LeaseApplication — müqavilə müraciət forması (18+ )

| # | Forma sahəsi | Model / snapshot key |
|---|--------------|----------------------|
| 1 | Şəxsin Adı | `person_name` |
| 2 | VÖEN | `tax_id` |
| 3 | Hüquqi ünvan | `legal_address` |
| 4 | Faktiki ünvan | `actual_address` |
| 5 | Mərtəbə | `floor_label` |
| 6 | Sahə | `space` FK + `space_label` |
| 7 | İstifadə təyinatı | `use_purpose` |
| 8 | 1 m² aylıq (ƏDV xaric) | `rent_rate_per_m2` |
| 9 | Aylıq ümumi (ƏDV xaric) | `monthly_rent_net` |
| 10 | Zəmanət | `deposit_amount` |
| 11 | Azadolma müddəti | `rent_free_note` |
| 12 | Təmizlik daxil? | `cleaning_included` |
| 13 | Çay xidməti daxil? | `tea_service_included` |
| 14 | İcarə başlanğıc | `lease_start` |
| 15 | İcarə bitmə | `lease_end` |
| 16 | Bank rekvizitləri | `bank_details` |
| 17 | Təmir qeydləri | `fit_out_notes` |
| 18 | Əlavə qeydlər | `extra_notes` |
| + | İmzalayan vəzifə/S.A.A. | `signer_title_name` |
| + | Əlavələr checklist | attachments JSON |

## Reminder qaydası

- Lid: `inquired_at`/`created_at` + **1 calendar day**, activity yoxdursa; closed/non_potential istisna; idempotent event_key.
- Offer: `sent_at` + **3 calendar days**, cavabsız; avto-expire yox.

## Scope

- Ofis/sahə icarəsi: bu modul.
- Meeting Room / website / reklam / Excel bulk import: Phase 2.
