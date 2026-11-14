"""LexiAfrik SDK — turn API payloads into models (shared by the sync and async clients)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import (
    AccountInfo, ApiKey, Language, NewApiKey, SegmentDetail, SegmentPage, SegmentResult, TranscriptionPage,
    TranscriptionResult, TranscriptionSummary, UsageDashboard,
)


def parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_segments(raw) -> List[SegmentResult]:
    return [
        SegmentResult(
            index=s["index"], start_s=s["start_s"], end_s=s["end_s"], duration_s=s["duration_s"],
            text=s.get("text") or "", inference_time_s=s.get("inference_time_s") or 0.0,
            rtf=s.get("rtf") or 0.0, sample_rate=s.get("sample_rate"), audio_url=s.get("audio_url"),
        )
        for s in (raw or [])
    ]


def parse_result(data: dict, request_id: str) -> TranscriptionResult:
    segs = parse_segments(data.get("segments"))
    return TranscriptionResult(
        request_id=request_id,
        text=data.get("full_text") or "",
        language=data.get("language"),
        duration_s=data.get("total_duration_s") or 0.0,
        n_segments=data.get("n_segments") or len(segs),
        segments=segs,
        title=data.get("title"),
        audio_url=data.get("audio_url"),
        sample_rate=data.get("sample_rate"),
        timestamp=parse_dt(data.get("timestamp")),
    )


def parse_languages(data: dict) -> List[Language]:
    return [Language(code=l["code"], name=l["name"], aliases=l.get("aliases") or [])
            for l in data.get("languages", [])]


def parse_account(d: dict) -> AccountInfo:
    return AccountInfo(
        plan=d["plan"], plan_name=d.get("plan_name") or d["plan"],
        quota_seconds=d.get("quota_seconds"), used_seconds=d.get("used_seconds") or 0.0,
        quota_remaining_seconds=d.get("quota_remaining_seconds"),
        wallet_usd=d.get("wallet_usd") or 0.0, wallet_minutes=d.get("wallet_minutes") or 0.0,
        period_end=str(d["period_end"]) if d.get("period_end") else None,
        wallet_expires_at=str(d["wallet_expires_at"]) if d.get("wallet_expires_at") else None,
        features=d.get("features") or {},
    )


def parse_history(d: dict, page: int, page_size: int) -> TranscriptionPage:
    items = [
        TranscriptionSummary(
            request_id=r["request_id"], status=r.get("status") or "", text=r.get("text"),
            title=r.get("source_title"), language=r.get("language"), duration_s=r.get("duration_s"),
            timestamp=str(r["timestamp"]) if r.get("timestamp") else None,
            error=r.get("error_message"), tags=r.get("tags") or [],
        )
        for r in d.get("items", [])
    ]
    return TranscriptionPage(items=items, total=d.get("total", len(items)), page=page, page_size=page_size)


def parse_segment_detail(s: Dict[str, Any]) -> SegmentDetail:
    return SegmentDetail(
        id=s["id"], index=s.get("segment_index"), start_s=s.get("start_s"), end_s=s.get("end_s"),
        text=s.get("text") or "", edited_text=s.get("edited_text"), tags=s.get("tags") or [],
        has_audio=bool(s.get("has_audio")), audio_url=s.get("audio_url"), languages=s.get("cs_languages") or [],
    )


def parse_segment_page(d: dict, offset: int, limit: Optional[int]) -> SegmentPage:
    items = [parse_segment_detail(s) for s in d.get("items", [])]
    return SegmentPage(items=items, total=d.get("total", len(items)), offset=offset, limit=limit)


def parse_key(k: Dict[str, Any]) -> ApiKey:
    return ApiKey(
        key_hash=k["key_hash"], name=k.get("name") or "", prefix=k.get("prefix") or "", tier=k.get("tier"),
        active=k.get("active") is not False, primary=bool(k.get("primary")), current=bool(k.get("current")),
        description=k.get("description"),
        created_at=str(k["created_at"]) if k.get("created_at") else None,
        last_used_at=str(k["last_used_at"]) if k.get("last_used_at") else None,
    )


def parse_new_key(d: Dict[str, Any]) -> NewApiKey:
    return NewApiKey(api_key=d["api_key"], key_hash=d["key_hash"], prefix=d.get("prefix") or "",
                     name=d.get("name") or "", tier=d.get("tier"))


def parse_dashboard(d: Dict[str, Any]) -> UsageDashboard:
    return UsageDashboard(
        period=d.get("period", ""), tier=d.get("tier", ""), today=d.get("today") or {}, month=d.get("month") or {},
        total_transcriptions=d.get("total_transcriptions") or 0, history=d.get("history") or [],
        last_7_days=d.get("last_7_days") or [], languages=d.get("languages") or {}, by_key=d.get("by_key") or [],
    )


def normalize_tags(tags) -> List[Dict[str, str]]:
    """Accept ``{"topic": "interview"}`` or ``[{"key": "topic", "value": "interview"}]``."""
    if isinstance(tags, dict):
        return [{"key": str(k), "value": str(v)} for k, v in tags.items()]
    return [{"key": str(t["key"]), "value": str(t.get("value", ""))} for t in tags]
