# Outlook → Portal elanları

Staff Outlook-dan bina xəbərdarlığını `CC-Office` (All Residents) qrupuna BCC ilə göndərir. Shared mailbox həmin qrupun üzvüdür; ERP Microsoft Graph ilə inbox oxuyur və **bina-ümumi** (`visibility=building`) `Announcement` yaradır. Məktubdakı fayllar avtomatik `AnnouncementAttachment` olur — portal Elanlar modalında Aç / Yüklə.

Əl ilə Admin elanı yalnız ehtiyat / düzəliş üçündür.

## Axın

1. Staff → Outlook → BCC `CC-Office`
2. `CC-Office` üzvləri + shared mailbox məktubu alır
3. `poll_outlook_announcements` Graph-dan oxuyur
4. Portal → Elanlar (bütün şirkətlər)

## NetAdmin checklist

1. Shared mailbox yaratmaq (məs. `erp-announcements@citypoint.az`)
2. Bu qutunu **CC-Office** üzvü etmək
3. Azure AD App Registration:
   - Application permission: `Mail.Read`
   - Admin consent
   - Tenant ID, Client ID, Client secret → yalnız server `.env` (repoya yazılmasın)
4. ERP serverindən outbound HTTPS: `login.microsoftonline.com`, `graph.microsoft.com`
5. Test: BCC `CC-Office` → mailbox Inbox-da görünür

## ERP `.env`

```bash
OUTLOOK_POLL_ON_START=1
OUTLOOK_POLL_INTERVAL=60
OUTLOOK_TENANT_ID=...
OUTLOOK_CLIENT_ID=...
OUTLOOK_CLIENT_SECRET=...
OUTLOOK_MAILBOX=erp-announcements@citypoint.az
```

`OUTLOOK_POLL_ON_START=1` olanda web entrypoint background poller işə salır (`var/outlook_announcements_poller.log`).

Bir dəfəlik:

```bash
python manage.py poll_outlook_announcements --once
```

Credentials yoxdursa poller soft-skip edir (web düşmür).

## Dedup

`Announcement.external_message_id` = Graph `internetMessageId` (unique). Eyni məktub ikinci poll-da təkrar yaradılmır.

## Sərhədlər

- Yalnız `OUTLOOK_MAILBOX` oxunur
- Bu inteqrasiya **gələn** mail → elan; outbound elan göndərmə ayrı mövzudur
- Inline kiçik şəkil/logo attachment-ləri skip olunur; PDF və digər fayllar saxlanır
