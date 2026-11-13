"""Generate CRM/Sales (A.10) business questionnaire Word doc."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.shared import Cm, Pt


SECTIONS = [
    (
        "1. Modul sərhədi",
        "Bu blok CRM ilə Satışın eyni menyuda, yoxsa ayrı olacağını və huninin mərhələlərini müəyyən edir.",
        [
            {
                "q": "CRM və Satış ERP-də necə görünsün — bir blok, yoxsa iki ayrı menyu?",
                "what": "«Bir blok» o deməkdir ki, sidebar-da «CRM / Satış» altında Lidlər, İmkanlar, Təkliflər, Hunisi bir yerdədir. «İki menyu» o deməkdir ki, məsələn CRM = yalnız lid/əlaqə, Satış = təklif/müqavilə.",
                "why": "Nav strukturu, icazələr və hansı komandanın hansı ekranı açacağı buna bağlıdır. Səhv seçim sonradan ekranları parçalamağa və ya birləşdirməyə məcbur edir.",
                "hint": "Nümunə: «Bir blok — CRM/Satış»; və ya «İki menyu: CRM (lid) + Satış (təklif)».",
            },
            {
                "q": "Satış hunisinin mərhələləri hansılardır? Lid → İmkan → Təklif → İcarə (Lease) kifayətdirmi?",
                "what": "Huni = potensial müştərinin müqaviləyə qədər keçdiyi addımlar. Lid = maraqlanan; İmkan = ciddi danışıq; Təklif = yazılı kommersiya təklifi; Lease = icarə müqaviləsi qeydi.",
                "why": "Əlavə mərhələ (məs. sayt baxışı, LOI, hüquqi razılaşma) varsa, ekran, status və hesabat buna görə qurulmalıdır. Əks halda artıq mürəkkəblik yaranır.",
                "hint": "Nümunə: «Kifayətdir» və ya «Əlavə: Sayt baxışı, LOI».",
            },
            {
                "q": "Bu modul yalnız ofis/sahə icarəsi üçündür, yoxsa digər gəlir növləri də (event, reklam, fit-out podrat) CRM/Satışa düşür?",
                "what": "İndi sistem biznes mərkəzi sahə icarəsinə fokuslanır. Digər gəlirlər ayrıca proses və qiymət modeli tələb edə bilər.",
                "why": "Əhatə genişlənsə, təklif forması, məhsul tipi və hesabat dəyişir. Dar saxlamaq go-live-ı sürətləndirir.",
                "hint": "Nümunə: «Yalnız sahə icarəsi»; «Sonra event/reklam».",
            },
        ],
    ),
    (
        "2. Rollar və icazələr",
        "Kim lid/təklif yarada, kim təsdiq edə, kim müqaviləyə keçirə bilər — bunu aydınlaşdırır.",
        [
            {
                "q": "Yeni lid (maraqlanan şəxs/şirkət) yaratmaq kimə icazəli olsun?",
                "what": "Reception zəng/walk-in qəbul edir; Property kommersiya danışır; Management rəhbərlikdir. Bir neçə rol seçilə bilər.",
                "why": "Səhv icazə ya hər kəsin qarışıq lid yaratmasına, ya da Reception-ın qeyd edə bilməməsinə gətirib çıxarır.",
                "hint": "Nümunə: «Reception + Property + Management».",
            },
            {
                "q": "İmkan (Opportunity) və Təklif (Offer) yaratmaq / redaktə etmək kimə icazəli olsun?",
                "what": "İmkan = ciddi satış işi; Təklif = qiymət və şərtlər. Adətən kommersiya (Property) və rəhbərlik.",
                "why": "Qiymət və şərtləri yanlış rolun dəyişməsi maliyyə/müqavilə riskidir.",
                "hint": "Nümunə: «Yalnız Property və Management».",
            },
            {
                "q": "Təklifi qəbul edib Lease (icarə müqaviləsi draft) yaratmaq kimə icazəli olsun?",
                "what": "Bu addım sistemdə rəsmi icarə qeydini açır və sonradan billing-ə yol verir.",
                "why": "Kiminsə təsadüfən «qəbul» basması boş və ya səhv müqavilə yarada bilər.",
                "hint": "Nümunə: «Property; Management təsdiqindən sonra».",
            },
            {
                "q": "Admin (IT/sistem admin) CRM/Satış modulunu görüb işləyə bilsin, yoxsa yalnız Property + Management?",
                "what": "Finance-də A.7 kimi Admin-in görməməsi seçilmişdi. CRM üçün eyni və ya fərqli qayda ola bilər.",
                "why": "Adminə açmaq texniki dəstək asanlaşdırır; bağlamaq kommersiya məlumatını məhdudlaşdırır.",
                "hint": "Nümunə: «Admin görsün (read-only)» / «Admin görməsin».",
            },
            {
                "q": "Hər lid/imkan/təklif üçün məsul şəxs (owner) məcburi sahə olsunmu?",
                "what": "Owner = bu işə cavabdeh əməkdaş. Filter və xatırlatmalar buna bağlanır.",
                "why": "Ownersuz qeydlər «heç kimin işi» olub itir. Məcburi etmək intizam yaradır, amma Reception üçün əlavə addım ola bilər.",
                "hint": "Nümunə: «Bəli, məcburi»; «İxtiyari, default yaradan şəxs».",
            },
        ],
    ),
    (
        "3. Lid (Lead) — potensial kiracı",
        "Lid = hələ müqaviləsi olmayan, amma marağı olan şəxs/şirkət qeydi.",
        [
            {
                "q": "Lid mənbələrinin son siyahısı hansıdır?",
                "what": "Sistemdə hazırda: website, telefon, email, walk-in, referral, manual, other. Broker, LinkedIn, event və s. əlavə oluna bilər.",
                "why": "Mənbə hesabatı «haradan gəlir» göstərir; marketinq və Reception prosesi buna görə qurulur.",
                "hint": "Siyahını yazın və ya «mövcud siyahı kifayətdir» deyin.",
            },
            {
                "q": "Lid yaratarkən hansı sahələr məcburi olsun?",
                "what": "Məsələn: ad, telefon və/və ya email, şirkət adı, maraqlı sahə/m², büdcə, qeyd.",
                "why": "Həddən artıq məcburi sahə Reception-ı yavaşladır; çox azı isə sonradan əlaqəni mümkünsüz edir.",
                "hint": "Nümunə: «Ad + telefon məcburi; email/şirkət ixtiyari».",
            },
            {
                "q": "Lid statusları hansılar olsun və nə deməkdir?",
                "what": "Hazırda: Yeni, Keyfiyyətli (qualified), Keyfiyyətsiz (disqualified), Çevrilib (converted). Əlavə: «Əlaqə qurulur», «Gözləmə» və s.",
                "why": "Status hunisi və KPI-ləri idarə edir; qeyri-müəyyən status hesabatı pozur.",
                "hint": "Mövcud statusları təsdiq edin və ya dəyişiklik yazın.",
            },
            {
                "q": "Eyni email/telefon/şirkət təkrar gələndə nə olsun (duplicate)?",
                "what": "Seçimlər: xəbərdarlıq göstər; avtomatik mövcud lidə bağla; həmişə yeni yaz; əl ilə birləşdir.",
                "why": "Duplicate-lər hunini şişirdir və eyni müştəriyə iki nəfərin zəng etməsinə səbəb olur.",
                "hint": "Nümunə: «Xəbərdarlıq + mövcud lidə keçid».",
            },
            {
                "q": "Website-dən avtomatik lid (B.4) go-live üçün lazımdır, yoxsa yalnız əl ilə qeyd kifayətdir?",
                "what": "Air-gap/LAN mühitdə website→ERP birbaşa olmaya bilər; VPN/relay və ya sonra əlavə olunur.",
                "why": "«Website lid» DoD-ni bloklamamaq üçün aydın qərar lazımdır; əks hala stub «hazır» kimi qalır, trafik gəlmir.",
                "hint": "Nümunə: «İndi yalnız əl ilə»; «LAN-da website lazımdır».",
            },
        ],
    ),
    (
        "4. İmkan (Opportunity)",
        "İmkan = lid keyfiyyətli sayılıb ciddi danışıq/satış işinə çevrilmiş mərhələ.",
        [
            {
                "q": "İmkan həmişə liddən yaransın, yoxsa birbaşa da açıla bilsin (məs. mövcud rezident əlavə sahə istəyir)?",
                "what": "Mövcud kiracı genişlənmə istəyəndə yeni «lid» mənasız ola bilər; birbaşa İmkan/Təklif daha təbii olur.",
                "why": "Proses və UI: «yalnız liddən» sadədir; «birbaşa da» real əməliyyata uyğundur.",
                "hint": "Nümunə: «Hər ikisi — lid və birbaşa».",
            },
            {
                "q": "Commercial ticket → Opportunity axını saxlanılsınmı? Hansı ticket növləri CRM-ə düşməlidir?",
                "what": "Sistemdə CRM-eligible ticket-lərdən «Opportunity yarat» düyməsi var (məs. sahə genişlənmə, kommersiya sorğusu).",
                "why": "Service Desk növbəsi ilə satış hunisinin qarışmaması üçün sərhəd lazımdır.",
                "hint": "Nümunə: «Bəli saxla; yalnız crm_eligible altkateqoriyalar».",
            },
            {
                "q": "İmkan «Lost» (itirildi) olanda səbəb siyahısı lazımdırmı?",
                "what": "Məsələn: qiymət, rəqib bina, yer/mərtəbə, timing, büdcə yoxdur, cavabsız.",
                "why": "Rəhbərlik niyə uduzduğunu görə bilər; səbəbsiz Lost hesabatı boş qalır.",
                "hint": "Səbəbləri yazın və ya «ixtiyari mətn kifayətdir».",
            },
            {
                "q": "Bir İmkan altında bir neçə sahə (Space) seçilə bilməlidirmi?",
                "what": "Bəzi müştərilər 2–3 ofis və ya ofis+anbar istəyir; təklif də çoxsətirli ola bilər.",
                "why": "Tək sahə sadədir; çoxsahə model və PDF-i mürəkkəbləşdirir.",
                "hint": "Nümunə: «MVP-də bir sahə; sonra çoxsahə».",
            },
        ],
    ),
    (
        "5. Təklif (Offer) və qiymət",
        "Təklif = yazılı kommersiya şərtləri (sahə, kirayə, SC, müddət və s.).",
        [
            {
                "q": "Təklifdə qiymət necə hesablansın: m² × tarif (A.4), sabit aylıq məbləğ, yoxsa hər ikisi?",
                "what": "A.4 qərarı: icarə adətən rentable m² × AZN/m² (ƏDV-siz). Bəzən razılaşdırılmış sabit məbləğ də olur.",
                "why": "Billing və faktura eyni məntiqlə işləməlidir; təkliflə lease uyğunsuz olsa mübahisə yaranır.",
                "hint": "Nümunə: «Əsas m²×tarif; istisna olaraq sabit override».",
            },
            {
                "q": "Təklif formasında hansı sahələr məcburi olsun (SC, depozit, parkinq qeydi, fit-out, digər)?",
                "what": "A.4: parkinq ödənişsiz müqavilədə qeyd; depozit adətən 2 ay; SC ayrıca; fit-out avtomatik güzəşt yox.",
                "why": "Boş buraxılan sahələr sonra lease və fakturada sürpriz yaradır.",
                "hint": "Məcburi siyahını yazın.",
            },
            {
                "q": "Təklifin default etibar müddəti (valid_until) neçə gün olsun?",
                "what": "Məsələn 7, 14 və ya 30 gün. Müddət bitəndə təklif «köhnəlmiş» sayılır.",
                "why": "Köhnə qiymətlə qəbul riskini azaldır; follow-up prosesini dəqiq edir.",
                "hint": "Nümunə: «14 gün».",
            },
            {
                "q": "Eyni İmkan üçün bir neçə təklif versiyası (reviziya) lazımdırmı?",
                "what": "Məsələn v1 göndərildi, müştəri endirim istədi, v2 yaradıldı. Köhnə versiya tarixçədə qalır.",
                "why": "Tək təklifi overwrite etmək audit və «nə razılaşdıq» izini itirir.",
                "hint": "Nümunə: «Bəli, versiyalar»; «MVP-də bir aktiv təklif».",
            },
            {
                "q": "Endirim / xüsusi şərt olanda kim təsdiq edir və limit varmı (faiz və ya AZN)?",
                "what": "Məsələn 5%-ə qədər Property; üstü Management.",
                "why": "Nəzarətsiz endirim marjanı və A.4/A.7 uyğunluğunu pozur.",
                "hint": "Nümunə: «≤5% Property; >5% Management».",
            },
        ],
    ),
    (
        "6. Təsdiq (Approval) və sənədlər",
        "Kim təklifi rəsmən göndərə / qəbul edə bilər və PDF harada yaşayır.",
        [
            {
                "q": "Təklif müştəriyə göndərilməzdən əvvəl daxili təsdiq lazımdırmı? Kim?",
                "what": "Seçimlər: təsdiqsiz göndər; Property; Management; əvvəl Property sonra Management.",
                "why": "A.7 approval matrix-in CRM hissəsidir; boş qalsa ya hamı göndərir, ya heç kim.",
                "hint": "Nümunə: «Göndərmədən əvvəl Management».",
            },
            {
                "q": "Hansı məbləğ və ya sahə (m²) həddindən yuxarı ikinci imza (Management) məcburi olsun?",
                "what": "Kiçik ofislər sürətli keçsin; böyük deal-lər rəhbərlikdə dayansın.",
                "why": "Hədd olmadan ya hər şey yavaşlayır, ya böyük risklər nəzarətsiz qalır.",
                "hint": "Nümunə: «>50.000 AZN/il və ya >200 m² → Management».",
            },
            {
                "q": "Təklif PDF şablonu varmı? Dil (AZ/EN/RU), logo, hüquqi mətn kim tərəfindən veriləcək?",
                "what": "PDF olmadan təklif yalnız ekranda qalır; müştəriyə göndərmək üçün şablon lazımdır.",
                "why": "Şablon geciksə Phase 4 DoD «offer PDF» natamam qalır.",
                "hint": "«Şablon əlavə olunacaq (fayl adı…)» / «Əvvəlcə ekran, PDF sonra».",
            },
            {
                "q": "Qəbul olunmuş təklifdən sonra hüquqi müqavilə PDF-i CRM modulunda saxlansın, yoxsa Lease / Documents-də?",
                "what": "CRM = satış; Lease/Documents = rəsmi müqavilə arxivi. Təkrar saxlama qarışıqlıq yarada bilər.",
                "why": "SoT (single source of truth) aydın olmalıdır — audit və portal sənədləri üçün.",
                "hint": "Nümunə: «Müqavilə yalnız Lease/Documents; CRM-də link».",
            },
        ],
    ),
    (
        "7. Lease keçidi və digər modullarla əlaqə",
        "Təklif qəbulundan sonra icarə qeydi və şirkət (party) nə vaxt yaranır.",
        [
            {
                "q": "Offer accept sonrası Lease hansı statusda açılsın (draft, negotiation, signed…)?",
                "what": "Draft = hələ imzasız; Signed/Active = artıq rəsmi. Billing adətən Active + billing_active tələb edir.",
                "why": "Səhv status dərhal charge/faktura yarada və ya əksinə prosesi dayandıra bilər.",
                "hint": "Nümunə: «Həmişə Draft; imza ayrı addım».",
            },
            {
                "q": "Yeni şirkət/party nə vaxt yaradılsın — lid mərhələsində, təklifdə, yoxsa yalnız qəbulda?",
                "what": "Party = sistemdə şirkət/şəxs master qeydi (lease, invoice, portal buna bağlanır).",
                "why": "Tez yaratmaq duplicate party riski; gec yaratmaq isə təklifi «boş» saxlayır.",
                "hint": "Nümunə: «Qualify/İmkan zamanı party bağla və ya yarat».",
            },
            {
                "q": "Mövcud rezident əlavə sahə götürəndə: yeni Lease, yoxsa mövcud müqaviləyə amendment (əlavə)?",
                "what": "Yeni lease = ayrıca müqavilə kodu; amendment = parent_lease ilə bağlı dəyişiklik.",
                "why": "Billing, depozit və xitam qaydaları fərqlənir; hüquqi praktikanıza uyğun seçilməlidir.",
                "hint": "Nümunə: «Adətən yeni lease»; «Böyük dəyişiklikdə amendment».",
            },
        ],
    ),
    (
        "8. Proses və SLA",
        "Vaxt intizamı: nə qədər tez cavab, xatırlatma, müddəti bitmiş təklif.",
        [
            {
                "q": "Yeni lidə ilk cavab üçün hədəf müddət varmı (saat/gün)?",
                "what": "Məsələn 4 iş saatı və ya 1 iş günü. Sistem xatırlatma/KPI göstərə bilər.",
                "why": "Gec cavab conversion-u aşağı salır; hədəf olmadan KPI boşdur.",
                "hint": "Nümunə: «1 iş günü»; «SLA yox, yalnız manual».",
            },
            {
                "q": "Təklif göndərildikdən sonra follow-up xatırlatma lazımdırmı? Neçə gündən bir?",
                "what": "Məsələn 3 və 7-ci günə tapşırıq/bildiriş.",
                "why": "Göndərilib unudulan təkliflər hunidə «ölü» qalır.",
                "hint": "Nümunə: «3 gün sonra xatırlat»; «Lazım deyil».",
            },
            {
                "q": "Etibar müddəti bitmiş təklif avtomatik expired/rejected statusuna keçsinmi?",
                "what": "Avtomatik bağlama tarixçəni təmiz saxlayır; əl ilə bağlama isə çeviklik verir.",
                "why": "Köhnə «sent» təkliflər pipeline məbləğini şişirdə bilər.",
                "hint": "Nümunə: «Bəli, avtomatik expired»; «Xeyr, əl ilə».",
            },
        ],
    ),
    (
        "9. Hunisi, hesabat və bildiriş",
        "Rəhbərlik nəyi izləsin və status dəyişəndə kim xəbərdar olsun.",
        [
            {
                "q": "Rəhbərlik üçün əsas KPI-lər hansılardır?",
                "what": "Məsələn: yeni lid sayı, conversion % (lid→lease), orta cycle günü, açıq pipeline AZN, uduzma səbəbləri.",
                "why": "Hesabat ekranı və dashboard buna görə qurulur; hər metrik əlavə işdir.",
                "hint": "3–5 əsas metriki seçin.",
            },
            {
                "q": "Hunisi görünüşü: Kanban lövhə (sütunlar), yoxsa cədvəl + filter kifayətdir?",
                "what": "Kanban vizualdır, sürüklə-burax status dəyişir; cədvəl daha sadə və sürətli qurulur.",
                "why": "UI mürəkkəbliyi və sprint həcmi buna bağlıdır.",
                "hint": "Nümunə: «Əvvəl cədvəl; Kanban sonra».",
            },
            {
                "q": "Status dəyişəndə (yeni lid, təklif göndərildi, qəbul) kimə in-app və/və ya email bildiriş getsin?",
                "what": "Owner, Management, Reception və s. seçilə bilər.",
                "why": "Həddən artıq mail ignore olunur; az bildirmək isə deal-i gecikdirir.",
                "hint": "Nümunə: «Owner + Management; email yalnız qəbul/rejected».",
            },
        ],
    ),
    (
        "10. Dil, demo və go-live",
        "İstifadə dili, nümunə data və menyunun nə vaxt açılacağı.",
        [
            {
                "q": "CRM/Satış UI dil prioriteti hansıdır (AZ / EN / RU)?",
                "what": "Sistem çoxdillidir; əsas dil təlim və PDF default-unu müəyyən edir.",
                "why": "Tərcümə və şablon sırası buna görə planlaşdırılır.",
                "hint": "Nümunə: «AZ əsas; EN ikinci».",
            },
            {
                "q": "Demo/seed üçün neçə nümunə lid, imkan və təklif kifayətdir?",
                "what": "Təqdimat və test üçün hazır nümunələr (məs. 5 lid, 2 təklif, 1 qəbul→lease).",
                "why": "Boş modul demo-da «işləmir» təəssüratı yaradır.",
                "hint": "Nümunə: «5 lid / 3 imkan / 2 təklif».",
            },
            {
                "q": "ERP sidebar-da CRM menyusu (nav_crm) nə vaxt açılsın — indi (qismən), yoxsa modul hazır olandan sonra?",
                "what": "Hazırda MVP üçün nav_crm gizlidir; birbaşa URL ilə listlər var.",
                "why": "Tez açmaq natamam UI göstərir; gec açmaq isə istifadəyə başlamağı gecikdirir.",
                "hint": "Nümunə: «CRUD hazır olandan sonra aç».",
            },
        ],
    ),
]


def add_answer_block(doc: Document) -> None:
    p = doc.add_paragraph()
    run = p.add_run("Cavab:")
    run.bold = True
    for _ in range(3):
        blank = doc.add_paragraph("_______________________________________________")
        blank.paragraph_format.space_after = Pt(2)


def build(path: Path) -> None:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2)
    section.right_margin = Cm(2)

    title = doc.add_heading("City Point — CRM / Satış modul sualları", level=0)
    title.runs[0].font.size = Pt(20)

    intro = doc.add_paragraph()
    intro.add_run(
        "Məqsəd: Tam funksional CRM/Satış (Phase 4) qurmazdan əvvəl biznes qərarlarını toplamaq. "
        "Lid = potensial kiracı qeydi; İmkan = ciddi danışıq; Təklif = kommersiya təklifi; "
        "Lease = icarə müqaviləsi sistem qeydi.\n\n"
        "Hər sualın altında «Cavab» sətirlərinə yazın. Cavablar BUSINESS_DECISIONS (A.10) və icra planına köçürüləcək.\n"
        "Tarix: ________________    Dolduran: ________________    Rol: ________________"
    )

    n = 0
    for section_title, section_blurb, questions in SECTIONS:
        doc.add_heading(section_title, level=1)
        blurb = doc.add_paragraph(section_blurb)
        blurb.runs[0].italic = True

        for item in questions:
            n += 1
            doc.add_heading(f"{n}. {item['q']}", level=2)

            p1 = doc.add_paragraph()
            r = p1.add_run("Nədir / izah: ")
            r.bold = True
            p1.add_run(item["what"])

            p2 = doc.add_paragraph()
            r = p2.add_run("Nə üçün lazımdır: ")
            r.bold = True
            p2.add_run(item["why"])

            p3 = doc.add_paragraph()
            r = p3.add_run("Cavab nümunəsi: ")
            r.bold = True
            p3.add_run(item["hint"])

            add_answer_block(doc)

    doc.add_heading("Əlavə qeydlər", level=1)
    doc.add_paragraph(
        "Buraya yuxarıya sığmayan proses, istisna və hüquqi tələbləri yazın:"
    )
    for _ in range(8):
        doc.add_paragraph("_______________________________________________")

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    print(f"Wrote {path} ({n} questions)")


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "CRM_Satis_Modul_Suallari_A10.docx"
    build(out)
