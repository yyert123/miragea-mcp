"""Voice, captions and scene narration on top of the Miragea API. No MCP imports here (easy to test)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from .captions import build_cues, to_srt, to_vtt, words
from .client import Client, MirageaError

MAX_CHARS = 1900  # API limit is 2000 per request; keep a margin
FORMATS = ("mp3", "wav", "flac", "opus", "aac")


# ---------------------------------------------------------------- helpers
def output_dir() -> Path:
    d = Path(os.environ.get("MIRAGEA_OUTPUT_DIR") or Path.home() / "Miragea").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:n].rstrip("-") or "speech")


def unique(path: Path) -> Path:
    """Never overwrite the user's files: add -2, -3, ... when the name is taken."""
    if not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def resolve_out(output_path: str | None, text: str, fmt: str) -> Path:
    if output_path:
        p = Path(output_path).expanduser()
        if not p.is_absolute():
            p = output_dir() / p
        if p.suffix.lower().lstrip(".") not in FORMATS:
            p = p.with_name(p.name + "." + fmt)
        p.parent.mkdir(parents=True, exist_ok=True)
        return unique(p)
    return unique(output_dir() / f"{slug(text)}.{fmt}")


def chunk_text(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Split at sentence ends (then commas, then spaces) so every piece is under the API limit."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return [text] if text else []
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?…])\s+", text):
        while len(sent) > limit:  # a monster sentence: cut at the last comma/space before the limit
            cut = max(sent.rfind(", ", 0, limit), sent.rfind(" ", 0, limit))
            cut = cut if cut > limit // 3 else limit
            head, sent = sent[:cut + 1].strip(), sent[cut + 1:].strip()
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(head)
        if cur and len(cur) + 1 + len(sent) > limit:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return parts


def wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def join_wavs(paths: list[Path], out: Path, gap: float = 0.12) -> None:
    with wave.open(str(paths[0])) as w0:
        params = w0.getparams()
    silence = b"\x00" * int(params.framerate * gap) * params.sampwidth * params.nchannels
    with wave.open(str(out), "wb") as o:
        o.setparams(params)
        for i, p in enumerate(paths):
            with wave.open(str(p)) as w:
                if (w.getframerate(), w.getsampwidth(), w.getnchannels()) != (params.framerate, params.sampwidth, params.nchannels):
                    raise MirageaError("Audio chunks came back in different formats.", "Re-run; this is unexpected.")
                if i:
                    o.writeframes(silence)
                o.writeframes(w.readframes(w.getnframes()))


def has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg"))


def encode(wav: Path, out: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), str(out)], check=True)


def voice_from(voice_id: str | None, reference_audio_url: str | None, reference_text: str | None) -> dict:
    voice_id = voice_id or (None if reference_audio_url else os.environ.get("MIRAGEA_VOICE_ID"))
    ref = reference_audio_url or (None if voice_id else os.environ.get("MIRAGEA_REF_URL"))
    if voice_id:
        return {"actor_id": voice_id}
    if ref:
        return {"reference_audio_url": ref, "reference_text": reference_text or os.environ.get("MIRAGEA_REF_TEXT")}
    raise MirageaError("No voice chosen.",
                       "Pass voice_id (call list_voices to see the voices saved in your Miragea account) or "
                       "reference_audio_url (a public URL of a clip you may clone) plus reference_text. "
                       "Set MIRAGEA_VOICE_ID in the server's env to make it the default.")


def cache_dir() -> Path:
    d = output_dir() / ".cache"
    d.mkdir(exist_ok=True)
    return d


def _speak_chunk(client: Client, text: str, voice: dict, model: str, speed: float | None) -> Path:
    key = hashlib.sha256(json.dumps([text, voice, model, speed], sort_keys=True).encode()).hexdigest()[:24]
    path = cache_dir() / f"{key}.wav"
    if not (path.exists() and path.stat().st_size > 100):
        tmp = path.with_name(path.stem + ".part.wav")
        client.speak(text, tmp, model=model, fmt="wav", speed=speed, **voice)
        tmp.replace(path)
    return path


# ---------------------------------------------------------------- tools
def speak(text: str, output_path: str | None = None, voice_id: str | None = None,
          reference_audio_url: str | None = None, reference_text: str | None = None, model: str = "expressive",
          speed: float | None = None, format: str = "mp3", client: Client | None = None) -> dict:
    if not text or not text.strip():
        raise MirageaError("Nothing to say.", "Pass the text to speak.")
    fmt = format.lower().lstrip(".")
    if fmt not in FORMATS:
        raise MirageaError(f"Unsupported format '{format}'.", f"Use one of: {', '.join(FORMATS)}.")
    voice = voice_from(voice_id, reference_audio_url, reference_text)
    client = client or Client()
    pieces = [_speak_chunk(client, c, voice, model, speed) for c in chunk_text(text)]
    note = None
    if fmt != "wav" and not has_ffmpeg():
        fmt, note = "wav", "Saved as WAV because ffmpeg is not installed (install ffmpeg for mp3/flac/opus/aac)."
    out = resolve_out(output_path, text, fmt)
    with tempfile.TemporaryDirectory() as td:
        joined = Path(td) / "joined.wav"
        join_wavs(pieces, joined) if len(pieces) > 1 else shutil.copy(pieces[0], joined)
        seconds = wav_duration(joined)
        shutil.copy(joined, out) if fmt == "wav" else encode(joined, out)
    res = {"path": str(out), "seconds": round(seconds, 3), "characters": len(text), "chunks": len(pieces),
           "voice": voice.get("actor_id") or "reference clip", "model": model}
    if note:
        res["note"] = note
    return res


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def transcript_of(path: Path, client: Client | None = None) -> dict:
    cache = cache_dir() / f"transcript-{_sha(path)}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    client = client or Client()
    with tempfile.TemporaryDirectory() as td:
        src = path
        if has_ffmpeg():  # upload a small 16 kHz mono track instead of a whole video
            src = Path(td) / "audio.flac"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(src)],
                           check=True)
        r = client.transcribe(src)
    data = {k: r.get(k) for k in ("text", "language", "segments")}
    cache.write_text(json.dumps(data, ensure_ascii=False))
    return data


def transcribe(path: str, style: str = "standard", output_dir_: str | None = None,
               client: Client | None = None) -> dict:
    src = Path(path).expanduser()
    if not src.exists():
        raise MirageaError(f"File not found: {src}", "Pass an absolute path to an audio or video file.")
    if style not in ("standard", "shorts"):
        raise MirageaError(f"Unknown style '{style}'.", "Use 'standard' (2 lines x 42 chars) or 'shorts' (1-3 words).")
    tr = transcript_of(src, client)
    cues = build_cues(words(tr), style, upper=(style == "shorts"))
    dest = Path(output_dir_).expanduser() if output_dir_ else src.parent
    if not os.access(dest, os.W_OK):
        dest = output_dir()
    stem = src.stem + (".shorts" if style == "shorts" else "")
    srt, vtt = unique(dest / f"{stem}.srt"), unique(dest / f"{stem}.vtt")
    srt.write_text(to_srt(cues), encoding="utf-8")
    vtt.write_text(to_vtt(cues), encoding="utf-8")
    return {"text": tr.get("text"), "language": tr.get("language"), "srt": str(srt), "vtt": str(vtt),
            "cues": len(cues), "seconds": round(cues[-1]["end"], 3) if cues else 0}


def remotion_captions(tr: dict, offset: float = 0.0) -> list[dict]:
    """Word-level captions in Remotion's Caption shape (@remotion/captions)."""
    return [{"text": (" " if i else "") + w["text"], "startMs": round((w["start"] + offset) * 1000),
             "endMs": round((w["end"] + offset) * 1000), "timestampMs": round(((w["start"] + w["end"]) / 2 + offset) * 1000),
             "confidence": None} for i, w in enumerate(words(tr))]


def narrate_scenes(scenes: list, output_dir_: str | None = None, fps: int = 30, voice_id: str | None = None,
                   reference_audio_url: str | None = None, reference_text: str | None = None,
                   model: str = "expressive", captions: bool = False, client: Client | None = None) -> dict:
    if not scenes:
        raise MirageaError("No scenes given.", "Pass a list of scene texts, or objects like {id, text}.")
    items = []
    for i, s in enumerate(scenes, 1):
        sid, text = (s.get("id") or f"scene-{i:02d}", s.get("text", "")) if isinstance(s, dict) else (f"scene-{i:02d}", str(s))
        if not text.strip():
            raise MirageaError(f"Scene {i} has no text.", "Give every scene some narration text.")
        items.append((slug(sid, 30), text))
    dest = Path(output_dir_).expanduser() if output_dir_ else output_dir() / "narration"
    dest.mkdir(parents=True, exist_ok=True)
    voice = voice_from(voice_id, reference_audio_url, reference_text)
    client = client or Client()
    out, t = [], 0.0
    fmt = "mp3" if has_ffmpeg() else "wav"
    all_caps: list[dict] = []
    for sid, text in items:
        pieces = [_speak_chunk(client, c, voice, model, None) for c in chunk_text(text)]
        f = dest / f"{sid}.{fmt}"  # stable names so a video project can reference them; regenerated in place
        with tempfile.TemporaryDirectory() as td:
            j = Path(td) / "j.wav"
            join_wavs(pieces, j) if len(pieces) > 1 else shutil.copy(pieces[0], j)
            secs = wav_duration(j)
            shutil.copy(j, f) if fmt == "wav" else encode(j, f)
            if captions:
                all_caps += remotion_captions(transcript_of(j, client), offset=t)
        frames = int(-(-secs * fps // 1))  # ceil, so audio is never cut off
        out.append({"id": sid, "file": str(f), "seconds": round(secs, 3), "durationInFrames": frames,
                    "startFrame": int(round(t * fps)), "text": text})
        t += frames / fps
    manifest = {"fps": fps, "totalSeconds": round(t, 3), "totalFrames": sum(s["durationInFrames"] for s in out),
                "scenes": out}
    if captions:
        cap = dest / "captions.json"
        cap.write_text(json.dumps(all_caps, indent=1))
        manifest["captions"] = str(cap)
    (dest / "narration.json").write_text(json.dumps(manifest, indent=2))
    manifest["manifest"] = str(dest / "narration.json")
    return manifest


def check_setup(client_factory=Client) -> dict:
    report: dict = {"api_key": bool(os.environ.get("MIRAGEA_API_KEY")), "ffmpeg": has_ffmpeg(),
                    "output_dir": str(output_dir()), "default_voice": os.environ.get("MIRAGEA_VOICE_ID") or
                    ("reference clip" if os.environ.get("MIRAGEA_REF_URL") else None), "problems": []}
    if not report["ffmpeg"]:
        report["problems"].append("ffmpeg not found: audio is saved as WAV and video files are uploaded whole. "
                                  "Install: brew install ffmpeg / sudo apt install ffmpeg / winget install ffmpeg.")
    if not report["api_key"]:
        report["problems"].append("MIRAGEA_API_KEY is not set. Create a key at https://miragea.ai and add it to this "
                                  "server's env in your MCP client config.")
        return report
    try:
        c = client_factory()
        caps = c.capabilities()
        report["models"] = [m.get("id") for m in caps.get("audio", {}).get("models", [])]
        report["max_chars_per_request"] = caps.get("audio", {}).get("max_text_length")
        report["caption_points_per_second"] = caps.get("subtitles", {}).get("points_per_second")
        v = c.voices(limit=50)
        report["saved_voices"] = len(v.get("items", []))
        if not v.get("items") and not report["default_voice"]:
            report["problems"].append("No saved voices in this Miragea account yet. Create one at https://miragea.ai, "
                                      "or pass reference_audio_url (a public clip) when speaking.")
    except MirageaError as exc:
        report["problems"].append(str(exc))
    report["ok"] = not report["problems"]
    return report
