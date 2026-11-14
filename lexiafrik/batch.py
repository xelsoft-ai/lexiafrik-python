"""LexiAfrik SDK — transcribe several files or a whole folder.

    from lexiafrik import LexiAfrikClient
    client = LexiAfrikClient()
    for item in client.transcribe_folder("interviews/", output_format="srt", jobs=3):
        print(item.status, item.path, item.error or "")

Each file is transcribed on its own: one failure never stops the others. Short audio files use the direct
route; large files and videos are uploaded and processed as asynchronous jobs.
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Union

from . import formats
from .exceptions import AudioTooLargeError, LexiAfrikError
from .models import FolderItem, TranscriptionResult

AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".weba", ".wma", ".amr"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mpeg", ".mpg", ".3gp", ".wmv"})
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
#: Above this size (or for a video), the asynchronous route is used. Below the API's own limit on purpose.
DIRECT_MAX_BYTES = 25 * 1024 * 1024


def find_media(path: Union[str, Path], recursive: bool = False) -> List[Path]:
    """Audio and video files of a folder (sorted); a single file is returned as is."""
    p = Path(path)
    if p.is_file():
        return [p]
    if not p.is_dir():
        raise LexiAfrikError(f"Not a file or folder: {path}")
    it = p.rglob("*") if recursive else p.glob("*")
    return sorted(f for f in it if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
                  and not f.name.startswith("."))


def output_path_for(src: Path, root: Optional[Path], out_dir: Optional[Union[str, Path]], fmt: str) -> Path:
    """Where the transcription of ``src`` is written: next to it, or under ``out_dir`` keeping the sub-folders."""
    name = src.stem + "." + fmt.lower().lstrip(".")
    if out_dir is None:
        return src.with_name(name)
    rel = src.parent.relative_to(root) if root and root.is_dir() else Path()
    return Path(out_dir) / rel / name


def transcribe_one(client, path: Union[str, Path], language: Optional[str] = None, keep_audio: bool = True,
                   want_segments: bool = True) -> TranscriptionResult:
    """Transcribe a single file with the right route (direct for short audio, asynchronous otherwise)."""
    p = Path(path)
    big = p.suffix.lower() in VIDEO_EXTENSIONS or p.stat().st_size > DIRECT_MAX_BYTES
    if not big:
        try:
            return client.transcribe(p, language=language, include_segments=want_segments, keep_audio=keep_audio)
        except AudioTooLargeError:
            pass  # the server's limit is lower than ours: fall back to the asynchronous route
    return client.transcribe_large(p, language=language, keep_audio=keep_audio)


def transcribe_files(
    client,
    files: Iterable[Union[str, Path]],
    *,
    language: Optional[str] = None,
    output_format: Optional[str] = None,
    out_dir: Optional[Union[str, Path]] = None,
    root: Optional[Union[str, Path]] = None,
    skip_existing: bool = True,
    jobs: int = 2,
    keep_audio: bool = True,
    on_item: Optional[Callable[[FolderItem], None]] = None,
) -> List[FolderItem]:
    """Transcribe ``files`` with ``jobs`` workers. Returns one :class:`FolderItem` per file, in input order.

    If ``output_format`` is given (``txt``, ``srt``, ``vtt`` or ``json``), each transcription is written to disk
    (see :func:`output_path_for`). With ``skip_existing`` a file whose output already exists is not sent again,
    so an interrupted run can simply be started again.
    """
    paths = [Path(f) for f in files]
    root_p = Path(root) if root else None
    if output_format:
        formats.render(TranscriptionResult(request_id="", text=""), output_format)  # validates the format early
    want_segments = (output_format or "").lower() in ("srt", "vtt", "json", "")
    lock = threading.Lock()
    results: dict = {}

    def work(i: int, src: Path) -> FolderItem:
        out = output_path_for(src, root_p, out_dir, output_format) if output_format else None
        if out is not None and skip_existing and out.exists():
            return FolderItem(path=str(src), status="skipped", output_path=str(out))
        try:
            res = transcribe_one(client, src, language, keep_audio, want_segments)
            if out is not None:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(formats.render(res, output_format), encoding="utf-8")
            return FolderItem(path=str(src), status="success", output_path=str(out) if out else None, result=res)
        except Exception as e:  # noqa: BLE001 — one bad file must not stop the batch
            return FolderItem(path=str(src), status="error", error=str(e) or type(e).__name__)

    with ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
        futures = {pool.submit(work, i, p): i for i, p in enumerate(paths)}
        for fut in as_completed(futures):
            item = fut.result()
            results[futures[fut]] = item
            if on_item:
                with lock:
                    on_item(item)
    return [results[i] for i in range(len(paths))]
