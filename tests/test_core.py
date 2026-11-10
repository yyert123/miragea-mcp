"""Offline tests: a fake Miragea client writes real WAV files, so the whole pipeline runs without a key."""
import json
import wave
from pathlib import Path

import pytest

from miragea_mcp import core
from miragea_mcp.client import MirageaError


class FakeClient:
    def __init__(self):
        self.calls = []

    def speak(self, text, out_path, **kw):
        self.calls.append((text, kw))
        n = int(16000 * (0.05 * len(text.split())))  # 50 ms per word
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x01\x00" * n)
        return Path(out_path)

    def transcribe(self, path):
        return {"text": "Hello world.", "language": "English",
                "segments": [{"start": 0.0, "end": 1.0, "text": "Hello wor"}, {"start": 1.0, "end": 1.5, "text": "ld."}]}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRAGEA_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("MIRAGEA_API_KEY", "test")
    for k in ("MIRAGEA_VOICE_ID", "MIRAGEA_REF_URL", "MIRAGEA_REF_TEXT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(core, "has_ffmpeg", lambda: False)  # pure-Python path
    return tmp_path


def test_chunking_respects_limit_and_keeps_all_text():
    text = " ".join(["A normal sentence, with a comma, for testing."] * 120)
    parts = core.chunk_text(text)
    assert len(parts) > 1 and all(len(p) <= core.MAX_CHARS for p in parts)
    assert " ".join(parts) == text
    giant = "word " * 1000  # no sentence end at all
    assert all(len(p) <= core.MAX_CHARS for p in core.chunk_text(giant))


def test_speak_long_text_joins_chunks_and_reports_exact_duration():
    fc = FakeClient()
    text = " ".join(["This is sentence number one of many."] * 80)
    r = core.speak(text, voice_id="v1", client=fc)
    assert r["chunks"] == len(fc.calls) > 1
    assert r["path"].endswith(".wav") and "note" in r  # no ffmpeg -> WAV with an explanation
    words = len(text.split())
    assert abs(r["seconds"] - (words * 0.05 + 0.12 * (r["chunks"] - 1))) < 0.02


def test_speak_never_overwrites_and_caches():
    fc = FakeClient()
    a = core.speak("Hello there.", voice_id="v1", format="wav", client=fc)
    b = core.speak("Hello there.", voice_id="v1", format="wav", client=fc)
    assert a["path"] != b["path"] and len(fc.calls) == 1  # second call served from cache, new file name


def test_voice_resolution_and_errors(monkeypatch):
    with pytest.raises(MirageaError, match="No voice"):
        core.speak("Hi.", client=FakeClient())
    monkeypatch.setenv("MIRAGEA_VOICE_ID", "env-voice")
    assert core.voice_from(None, None, None) == {"actor_id": "env-voice"}
    assert core.voice_from(None, "https://x/y.wav", "words")["reference_audio_url"] == "https://x/y.wav"
    with pytest.raises(MirageaError, match="Unsupported format"):
        core.speak("Hi.", format="midi", client=FakeClient())


def test_narrate_scenes_frames_and_captions(tmp_path):
    fc = FakeClient()
    m = core.narrate_scenes(["One two three four.", {"id": "Outro!", "text": "Bye now."}], str(tmp_path / "n"),
                            fps=30, voice_id="v", captions=True, client=fc)
    s1, s2 = m["scenes"]
    assert s1["durationInFrames"] == 6 and s2["startFrame"] == 6 and s2["id"] == "outro"
    assert m["totalFrames"] == s1["durationInFrames"] + s2["durationInFrames"]
    caps = json.loads(Path(m["captions"]).read_text())
    assert caps[0]["text"] == "Hello" and caps[1]["text"] == " world."  # whole words even when segments split
    assert caps[2]["startMs"] >= s2["startFrame"] / 30 * 1000 - 1  # second scene offset applied


def test_transcribe_writes_srt_vtt(tmp_path):
    f = tmp_path / "a.wav"
    FakeClient().speak("x y", f)
    r = core.transcribe(str(f), client=FakeClient())
    assert Path(r["srt"]).read_text().startswith("1\n00:00:00,000")
    assert Path(r["vtt"]).read_text().startswith("WEBVTT")
    with pytest.raises(MirageaError, match="not found"):
        core.transcribe(str(tmp_path / "missing.mp4"), client=FakeClient())


def test_check_setup_without_key(monkeypatch):
    monkeypatch.delenv("MIRAGEA_API_KEY")
    r = core.check_setup()
    assert r["api_key"] is False and any("MIRAGEA_API_KEY" in p for p in r["problems"])


def test_server_registers_tools():
    from miragea_mcp.server import build_server
    srv = build_server()
    import asyncio
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert names == {"check_setup", "list_voices", "speak", "transcribe", "narrate_scenes"}
