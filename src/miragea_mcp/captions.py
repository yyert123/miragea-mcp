"""Turn Miragea's segment transcript into readable caption cues (stdlib only).

Miragea segments are timed by audio, not by words, and can split mid-word
("cen" | "ts"). We place every character of the full transcript in time, rebuild
whole words, then group words into cues that follow subtitle conventions.
"""
from __future__ import annotations

import re

PRESETS = {
    # Netflix-style limits: 42 chars/line, 2 lines, 1-7 s, ~17 chars/s.
    "standard": {"max_chars": 42, "max_lines": 2, "max_dur": 7.0, "min_dur": 1.0, "max_words": 99},
    # Short-form vertical video: punchy 1-3 word cues, one line.
    "shorts": {"max_chars": 16, "max_lines": 1, "max_dur": 2.0, "min_dur": 0.35, "max_words": 3},
}


def char_times(text: str, segments: list) -> list:
    alnum_pos = [i for i, c in enumerate(text) if c.isalnum()]
    alnum = "".join(text[i].lower() for i in alnum_pos)
    times = [None] * len(text)
    cursor = 0
    for seg in segments:
        s = "".join(c.lower() for c in seg.get("text", "") if c.isalnum())
        if not s:
            continue
        at = alnum.find(s, cursor)
        if at < 0:
            at = alnum.find(s[:4], cursor)
            if at < 0:
                continue
        end = min(at + len(s), len(alnum_pos)) - 1
        n = max(1, end - at)
        for k in range(at, end + 1):
            times[alnum_pos[k]] = seg["start"] + (k - at) / n * (seg["end"] - seg["start"])
        cursor = end + 1
    known = [i for i, t in enumerate(times) if t is not None]
    if not known:
        return times
    j = 0
    for i in range(len(times)):
        if times[i] is None:
            while j + 1 < len(known) and known[j + 1] < i:
                j += 1
            left = known[j] if known[j] < i else None
            right = next((k for k in known[j:] if k > i), None)
            if left is None:
                times[i] = times[right]
            elif right is None:
                times[i] = times[left]
            else:
                times[i] = times[left] + (i - left) / (right - left) * (times[right] - times[left])
    return times


def words(transcript: dict) -> list:
    """Return [{'text', 'start', 'end'}] for every whole word."""
    text = transcript.get("text") or " ".join(s.get("text", "") for s in transcript.get("segments", []))
    times = char_times(text, transcript.get("segments", []))
    out = []
    for m in re.finditer(r"\S+", text):
        idx = [i for i in range(m.start(), m.end()) if text[i].isalnum()] or [m.start()]
        if times[idx[0]] is None:
            continue
        out.append({"text": m.group(), "start": times[idx[0]], "end": times[idx[-1]]})
    # A word ends where the next begins at the latest; give the last word its segment end.
    segs = transcript.get("segments") or []
    if out and segs:
        out[-1]["end"] = max(out[-1]["end"], segs[-1]["end"])
    for a, b in zip(out, out[1:]):
        a["end"] = max(a["end"], min(b["start"], a["start"] + 0.08))
    return out


def _wrap(text: str, max_chars: int, max_lines: int) -> str:
    if len(text) <= max_chars or max_lines == 1:
        return text
    ws = text.split()
    best, best_cost = text, 1e9
    for k in range(1, len(ws)):  # most balanced 2-line split
        a, b = " ".join(ws[:k]), " ".join(ws[k:])
        cost = abs(len(a) - len(b)) + (100 if max(len(a), len(b)) > max_chars else 0)
        if cost < best_cost:
            best, best_cost = a + "\n" + b, cost
    return best


def build_cues(ws: list, preset: str = "standard", upper: bool = False) -> list:
    p = PRESETS[preset]
    limit = p["max_chars"] * p["max_lines"]
    cues, cur = [], []

    def flush():
        if cur:
            txt = " ".join(w["text"] for w in cur)
            if preset == "shorts":
                txt = txt.strip(",;:")
            cues.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": txt.upper() if upper else txt})
            cur.clear()

    for w in ws:
        if cur:
            joined = len(" ".join(x["text"] for x in cur)) + 1 + len(w["text"])
            gap = w["start"] - cur[-1]["end"]
            if (joined > limit or len(cur) >= p["max_words"] or gap > 0.6
                    or w["end"] - cur[0]["start"] > p["max_dur"]):
                flush()
        cur.append(w)
        if re.search(r"[.!?…]['\")\]]*$", w["text"]) and not re.fullmatch(r"[A-Z]\.", w["text"]) and (preset == "shorts" or len(cur) >= 3):
            flush()
        elif preset == "standard" and re.search(r"[,;:—]$", w["text"]) and len(" ".join(x["text"] for x in cur)) > limit * 0.6:
            flush()
    flush()
    # Minimum on-screen time without overlapping the next cue.
    for a, b in zip(cues, cues[1:] + [None]):
        want = a["start"] + p["min_dur"]
        nxt = b["start"] - 0.04 if b else want
        a["end"] = max(a["end"], min(want, nxt))
    for c in cues:
        c["text"] = _wrap(c["text"], p["max_chars"], p["max_lines"])
    return cues


def _ts(t: float, sep: str) -> str:
    ms = int(round(max(t, 0) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def to_srt(cues: list) -> str:
    return "\n".join(f"{i}\n{_ts(c['start'], ',')} --> {_ts(c['end'], ',')}\n{c['text']}\n"
                     for i, c in enumerate(cues, 1))


def to_vtt(cues: list) -> str:
    return "WEBVTT\n\n" + "\n".join(f"{_ts(c['start'], '.')} --> {_ts(c['end'], '.')}\n{c['text']}\n" for c in cues)
