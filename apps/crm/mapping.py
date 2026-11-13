"""Excel / free-text → canonical CRM codes (see docs/architecture/CRM_FIELD_MAPPING.md)."""

from __future__ import annotations

from apps.crm.models import LeadSource, Outcome, PipelineStage, Qualification, RecordStatus

SOURCE_ALIASES: dict[str, str] = {
    "website": LeadSource.WEBSITE,
    "telefon": LeadSource.PHONE,
    "phone": LeadSource.PHONE,
    "e-mail": LeadSource.EMAIL,
    "email": LeadSource.EMAIL,
    "email marketing": LeadSource.EMAIL_MARKETING,
    "walk-in": LeadSource.WALK_IN,
    "walk in": LeadSource.WALK_IN,
    "yönləndirmə": LeadSource.REFERRAL,
    "referral": LeadSource.REFERRAL,
    "targeting": LeadSource.TARGETING,
    "targeting reklamı": LeadSource.TARGETING,
    "soyuq zənglər": LeadSource.COLD_CALL,
    "cold call": LeadSource.COLD_CALL,
    "sosial şəbəkə": LeadSource.SOCIAL_MEDIA,
    "smm": LeadSource.SOCIAL_MEDIA,
    "instagram": LeadSource.SOCIAL_MEDIA,
    "bilboard": LeadSource.BILLBOARD,
    "billboard": LeadSource.BILLBOARD,
    "birbaşa müraciət": LeadSource.DIRECT,
    "birbaşa görüşlər": LeadSource.DIRECT,
    "direct": LeadSource.DIRECT,
    "manual": LeadSource.MANUAL,
}

STAGE_ALIASES: dict[str, str] = {
    "yeni sorğu": PipelineStage.WORKING,
    "işlənilir": PipelineStage.WORKING,
    "cavab gözlənilir": PipelineStage.CONTACT_PENDING,
    "görüş təyin olunub": PipelineStage.MEETING_SCHEDULED,
    "sahəyə baxış": PipelineStage.VIEWING_SCHEDULED,
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
    "digər": Outcome.OTHER,
}

QUAL_ALIASES: dict[str, str] = {
    "qiymətləndirilməyib": Qualification.UNREVIEWED,
    "potensial": Qualification.POTENTIAL,
    "qeyri-potensial": Qualification.NON_POTENTIAL,
}


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def map_source(raw: str) -> tuple[str, str]:
    key = _norm(raw)
    if not key:
        return LeadSource.MANUAL, ""
    code = SOURCE_ALIASES.get(key)
    if code:
        return code, ""
    if key in {c.value for c in LeadSource}:
        return key, ""
    return LeadSource.OTHER, (raw or "")[:255]


def map_pipeline_stage(raw: str) -> str:
    key = _norm(raw)
    if key in {c.value for c in PipelineStage}:
        return key
    return STAGE_ALIASES.get(key, PipelineStage.WORKING)


def map_record_status(raw: str) -> str:
    key = _norm(raw)
    if key in {c.value for c in RecordStatus}:
        return key
    return RECORD_ALIASES.get(key, RecordStatus.OPEN)


def map_outcome(raw: str) -> str:
    key = _norm(raw)
    if key in {c.value for c in Outcome}:
        return key
    return OUTCOME_ALIASES.get(key, Outcome.OTHER)


def map_qualification(raw: str) -> str:
    key = _norm(raw)
    if key in {c.value for c in Qualification}:
        return key
    return QUAL_ALIASES.get(key, Qualification.UNREVIEWED)


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
