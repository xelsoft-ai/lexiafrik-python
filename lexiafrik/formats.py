"""LexiAfrik SDK — output formats for a transcription: plain text, SRT, WebVTT and JSON.

    from lexiafrik import formats
    open("talk.srt", "w", encoding="utf-8").write(formats.to_srt(result))

The same functions are available as methods: ``result.to_text()``, ``result.to_srt()``, ``result.to_vtt()``,
``result.to_json()``. SRT and WebVTT need timestamps: they use the segments of the result (ask for
``include_segments=True`` on a short file; asynchronous jobs always return them). Without segments, the
whole text becomes a single cue spanning the audio duration.
"""

import json
from typing import Any, List, Tuple

FORMATS = ("txt", "srt", "vtt", "json")


def _cues(result: Any) -> List[Tuple[float, float, str]]:
    segs = [s for s in (getattr(result, "segments", None) or []) if (s.text or "").strip()]
    if segs:
        return [(float(s.start_s), float(s.end_s), s.text.strip()) for s in segs]
    text = (getattr(result, "text", "") or "").strip()
    if not text:
        return []
    return [(0.0, float(getattr(result, "duration_s", 0.0) or 0.0), text)]


def _stamp(seconds: float, sep: str) -> str:
    ms = int(round(max(seconds, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_text(result: Any) -> str:
    """The transcription as plain text."""
    return (getattr(result, "text", "") or "").strip() + "\n"


def to_srt(result: Any) -> str:
    """SubRip subtitles (``.srt``)."""
    blocks = []
    for i, (start, end, text) in enumerate(_cues(result), 1):
        blocks.append(f"{i}\n{_stamp(start, ',')} --> {_stamp(end, ',')}\n{text}\n")
    return "\n".join(blocks)


def to_vtt(result: Any) -> str:
    """WebVTT subtitles (``.vtt``)."""
    blocks = ["WEBVTT\n"]
    for start, end, text in _cues(result):
        blocks.append(f"{_stamp(start, '.')} --> {_stamp(end, '.')}\n{text}\n")
    return "\n".join(blocks)


def to_json(result: Any, indent: int = 2) -> str:
    """The transcription and its segments as JSON."""
    data = {
        "request_id": getattr(result, "request_id", None),
        "language": getattr(result, "language", None),
        "duration_s": getattr(result, "duration_s", 0.0),
        "title": getattr(result, "title", None),
        "text": getattr(result, "text", ""),
        "segments": [
            {"index": s.index, "start_s": s.start_s, "end_s": s.end_s, "duration_s": s.duration_s, "text": s.text}
            for s in (getattr(result, "segments", None) or [])
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=indent) + "\n"


def render(result: Any, fmt: str) -> str:
    """Render ``result`` in one of ``FORMATS``."""
    fmt = fmt.lower().lstrip(".")
    fn = {"txt": to_text, "text": to_text, "srt": to_srt, "vtt": to_vtt, "json": to_json}.get(fmt)
    if fn is None:
        raise ValueError(f"Unknown format {fmt!r}: choose one of {', '.join(FORMATS)}.")
    return fn(result)
