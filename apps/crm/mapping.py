"""Excel / free-text → canonical CRM codes (see docs/architecture/CRM_FIELD_MAPPING.md)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from apps.crm.models import LeadSource, Outcome, PipelineStage, Qualification, RecordStatus

SOURCE_ALIASES: dict[str, str] = {
    "website": LeadSource.WEBSITE,
    "telefon": LeadSource.PHONE,
    "phone": LeadSource.PHONE,
    "e-mail": LeadSource.EMAIL,
    "email": LeadSource.EMAIL,
    "e-mail marketing": LeadSource.EMAIL_MARKETING,
    "email marketing": LeadSource.EMAIL_MARKETING,
    "walk-in": LeadSource.WALK_IN,
    "walk in": LeadSource.WALK_IN,
    "yönləndirmə": LeadSource.REFERRAL,
    "yonləndirmə": LeadSource.REFERRAL,
    "referral": LeadSource.REFERRAL,
    "targeting": LeadSource.TARGETING,
    "targeting reklamı": LeadSource.TARGETING,
    "soyuq zənglər": LeadSource.COLD_CALL,
    "soyuq zənqlər": LeadSource.COLD_CALL,  # Excel typo
    "cold call": LeadSource.COLD_CALL,
    "sosial şəbəkə": LeadSource.SOCIAL_MEDIA,
    "smm": LeadSource.SOCIAL_MEDIA,
    "instagram": LeadSource.SOCIAL_MEDIA,
    "insta": LeadSource.SOCIAL_MEDIA,
    "bilboard": LeadSource.BILLBOARD,
    "billboard": LeadSource.BILLBOARD,
    "birbaşa müraciət": LeadSource.DIRECT,
    "birbaşa görüşlər": LeadSource.DIRECT,
    "direct": LeadSource.DIRECT,
    "manual": LeadSource.MANUAL,
}

STAGE_ALIASES: dict[str, str] = {
    "yeni sorğu": PipelineStage.WORKING,
    "yeni sorğu/işlənilir": PipelineStage.WORKING,
    "işlənilir": PipelineStage.WORKING,
    "cavab gözlənilir": PipelineStage.CONTACT_PENDING,
    "görüş təyin olunub": PipelineStage.MEETING_SCHEDULED,
    "sahəyə baxış": PipelineStage.VIEWING_SCHEDULED,
    "sahəyə baxış planlaşdırılıb": PipelineStage.VIEWING_SCHEDULED,
    "sahəyə baxış keçirilib": PipelineStage.VIEWING_COMPLETED,
    "danışıqlar mərhələsində": PipelineStage.NEGOTIATION,
    "danışıqlar": PipelineStage.NEGOTIATION,
    "təklif göndərilib": PipelineStage.OFFER_SENT,
    "müqavilə mərhələsində": PipelineStage.LEASE_STAGE,
    "əməkdaşlıq": PipelineStage.WON,
    "qazanıldı": PipelineStage.WON,
    "itirildi": PipelineStage.LOST,
    "gözləntidə": PipelineStage.ON_HOLD,
}

RECORD_ALIASES: dict[str, str] = {
    "açıqdır": RecordStatus.OPEN,
    "açıq": RecordStatus.OPEN,
    "gözləntidə": RecordStatus.WAITING,
    "bağlıdır": RecordStatus.CLOSED,
    "bağlı": RecordStatus.CLOSED,
}

OUTCOME_ALIASES: dict[str, str] = {
    "əməkdaşlıq təmin olunub": Outcome.COOPERATION_SECURED,
    "təklif qəbul olunmayıb": Outcome.OFFER_REJECTED,
    "müştəri geri dönüş etməyib": Outcome.NO_RESPONSE,
    "geri dönüş yoxdur": Outcome.NO_RESPONSE,
    "maraqlı deyil": Outcome.NOT_INTERESTED,
    "köçüblər": Outcome.NOT_INTERESTED,
    "yanlış sorğu": Outcome.INVALID_REQUEST,
    "qiymət": Outcome.PRICE,
    "sahə": Outcome.AREA,
    "parkinq": Outcome.PARKING,
    "digər": Outcome.OTHER,
}

QUAL_ALIASES: dict[str, str] = {
    "qiymətləndirilməyib": Qualification.UNREVIEWED,
    "potensial": Qualification.POTENTIAL,
    "qeyri-potensial": Qualification.NON_POTENTIAL,
}

_AREA_RANGE_RE = re.compile(
    r"(?P<a>\d+(?:[.,]\d+)?)\s*(?:-|–|—|/|to)\s*(?P<b>\d+(?:[.,]\d+)?)",
    re.I,
)
_AREA_SINGLE_RE = re.compile(r"(?P<a>\d+(?:[.,]\d+)?)")


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _alias_lookup(aliases: dict[str, str], key: str) -> str | None:
    if key in aliases:
        return aliases[key]
    # Partial: "yeni sorğu/işlənilir", "sahəyə baxış keçirilib …"
    for alias, code in sorted(aliases.items(), key=lambda x: -len(x[0])):
        if alias and alias in key:
            return code
    return None


def map_source(raw: str) -> tuple[str, str]:
    key = _norm(raw)
    if not key:
        return LeadSource.MANUAL, ""
    code = _alias_lookup(SOURCE_ALIASES, key)
    if code:
        return code, ""
    if key in {c.value for c in LeadSource}:
        return key, ""
    return LeadSource.OTHER, (raw or "")[:255]


def map_pipeline_stage(raw: str) -> str:
    key = _norm(raw)
    if not key or key in {"-", "—"}:
        return PipelineStage.WORKING
    if key in {c.value for c in PipelineStage}:
        return key
    return _alias_lookup(STAGE_ALIASES, key) or PipelineStage.WORKING


def map_record_status(raw: str) -> str:
    key = _norm(raw)
    if not key or key in {"-", "—"}:
        return RecordStatus.OPEN
    if key in {c.value for c in RecordStatus}:
        return key
    return _alias_lookup(RECORD_ALIASES, key) or RecordStatus.OPEN


def map_outcome(raw: str) -> str:
    key = _norm(raw)
    if not key or key in {"-", "—"}:
        return ""
    if key in {c.value for c in Outcome}:
        return key
    return _alias_lookup(OUTCOME_ALIASES, key) or Outcome.OTHER


def infer_outcome_from_notes(notes: str, *, existing: str = "") -> str:
    """Qeyd mətnindən yüngül səbəb — yalnız outcome boş olanda."""
    if (existing or "").strip():
        return existing
    text = _norm(notes)
    if not text:
        return ""
    if "yanlış sorğu" in text or "adboy" in text:
        return Outcome.INVALID_REQUEST
    if any(x in text for x in ("qiymət bahadır", "qiymət uyğun", "bahadır", "qiymət baha")):
        return Outcome.PRICE
    if any(x in text for x in ("sahə uyğun", "sahə böyük", "sahə kiçik", "uyğun deyil")):
        return Outcome.AREA
    if "parkinq" in text:
        return Outcome.PARKING
    if "cavab yox" in text or "geri dönüş edilmədi" in text:
        return Outcome.NO_RESPONSE
    return ""


def map_qualification(raw: str) -> str:
    key = _norm(raw)
    if key in {c.value for c in Qualification}:
        return key
    return QUAL_ALIASES.get(key, Qualification.UNREVIEWED)


def parse_area_range(raw: str) -> tuple[Decimal | None, Decimal | None, str]:
    """`80-100 kv` / `175 kv 7-ci m` → (min, max, note)."""
    text = (raw or "").strip()
    if not text or text in {"-", "—"}:
        return None, None, ""
    note = text
    cleaned = re.sub(r"(?i)\bkv\.?\b|\bm2\b|\bm²\b", " ", text)
    cleaned = cleaned.replace(",", ".")

    def _dec(s: str | None) -> Decimal | None:
        if not s:
            return None
        try:
            return Decimal(s)
        except (InvalidOperation, ValueError):
            return None

    match = _AREA_RANGE_RE.search(cleaned)
    if match:
        a = _dec(match.group("a"))
        b = _dec(match.group("b"))
        if a is not None and b is not None:
            return min(a, b), max(a, b), note[:255]
    single = _AREA_SINGLE_RE.search(cleaned)
    if single:
        a = _dec(single.group("a"))
        return a, a, note[:255]
    return None, None, note[:255]


def legacy_status_to_fields(status: str) -> dict:
    """Map old Lead.status → qualification / record_status / pipeline_stage."""
    if status == "qualified":
        return {
            "qualification": Qualification.POTENTIAL,
            "record_status": RecordStatus.OPEN,
            "pipeline_stage": PipelineStage.WORKING,
        }
    if status == "disqualified":
        return {
            "qualification": Qualification.NON_POTENTIAL,
            "record_status": RecordStatus.CLOSED,
            "pipeline_stage": PipelineStage.LOST,
            "outcome": Outcome.INVALID_REQUEST,
        }
    if status == "converted":
        return {
            "qualification": Qualification.POTENTIAL,
            "record_status": RecordStatus.CLOSED,
            "pipeline_stage": PipelineStage.WON,
            "outcome": Outcome.COOPERATION_SECURED,
        }
    return {
        "qualification": Qualification.UNREVIEWED,
        "record_status": RecordStatus.OPEN,
        "pipeline_stage": PipelineStage.WORKING,
    }
