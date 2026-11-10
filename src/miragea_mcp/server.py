"""MCP server (stdio) exposing Miragea voice and captions to Claude, Cursor, Codex and other MCP clients."""
from __future__ import annotations

import json
import sys
from typing import Any, Optional, Union

from . import __version__, core
from .client import Client, MirageaError

INSTRUCTIONS = (
    "Voiceover, voice cloning and captions via the Miragea API. Start with check_setup if unsure. "
    "Use list_voices to find the user's saved voices; speak for any text (long text is split and joined "
    "automatically); transcribe for SRT/VTT captions of a local audio/video file; narrate_scenes for "
    "per-scene audio with exact durations (Remotion/HyperFrames/video timelines). Files are written to "
    "MIRAGEA_OUTPUT_DIR (default ~/Miragea) unless a path is given, and existing files are never overwritten. "
    "Only clone voices the user owns or has permission to use."
)


def _safe(fn, *a, **kw) -> dict:
    try:
        return fn(*a, **kw)
    except MirageaError as exc:  # return a readable error with the fix instead of a stack trace
        return {"error": str(exc).split("\n")[0], "how_to_fix": exc.hint or None}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}", "how_to_fix": "Check the input paths and try again."}


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:  # MCP SDK 2.x
        from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore
    mcp = FastMCP("miragea", instructions=INSTRUCTIONS)

    @mcp.tool()
    def check_setup() -> dict:
        """Check the API key, ffmpeg, saved voices and output folder, with a fix for every problem found."""
        return _safe(core.check_setup)

    @mcp.tool()
    def list_voices(limit: int = 50, offset: int = 0) -> dict:
        """List voices saved in the user's Miragea account (ids to pass as voice_id)."""
        def run():
            r = Client().voices(limit, offset)
            return {"voices": [{"voice_id": v.get("actor_id") or v.get("id"), "name": v.get("name")}
                               for v in r.get("items", [])], "has_more": r.get("has_more", False)}
        return _safe(run)

    @mcp.tool()
    def speak(text: str, output_path: Optional[str] = None, voice_id: Optional[str] = None,
              reference_audio_url: Optional[str] = None, reference_text: Optional[str] = None,
              model: str = "expressive", speed: Optional[float] = None, format: str = "mp3") -> dict:
        """Turn text of any length into speech in a saved voice (voice_id) or a voice cloned from a public
        clip (reference_audio_url + its exact words in reference_text, billed at the cheaper 1x rate).
        Returns the saved file path and its exact duration in seconds. format: mp3, wav, flac, opus, aac.
        model: 'expressive' (default) or 'standard'. speed: 0.25-4."""
        return _safe(core.speak, text, output_path, voice_id, reference_audio_url, reference_text, model, speed, format)

    @mcp.tool()
    def transcribe(path: str, style: str = "standard", output_dir: Optional[str] = None) -> dict:
        """Transcribe a local audio or video file into readable SRT and VTT captions (whole words, line-length
        and timing rules applied). style: 'standard' (2 lines x 42 chars) or 'shorts' (1-3 words, uppercase).
        Results are cached, so asking again for the same file is free."""
        return _safe(core.transcribe, path, style, output_dir)

    @mcp.tool()
    def narrate_scenes(scenes: list[Union[str, dict[str, Any]]], output_dir: Optional[str] = None, fps: int = 30,
                       voice_id: Optional[str] = None, reference_audio_url: Optional[str] = None,
                       reference_text: Optional[str] = None, model: str = "expressive",
                       captions: bool = False) -> dict:
        """Voice a list of scenes (strings or {id, text}) as one audio file per scene and return each scene's
        exact seconds, durationInFrames and startFrame at the given fps, plus a narration.json manifest.
        captions=true also writes word-level captions.json in Remotion's Caption format. Unchanged scenes are
        cached and cost nothing on re-runs."""
        return _safe(core.narrate_scenes, scenes, output_dir, fps, voice_id, reference_audio_url, reference_text,
                     model, captions)

    return mcp


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-V", "--version"):
        print(f"miragea-mcp {__version__}")
        return 0
    if argv and argv[0] in ("--check", "check"):
        print(json.dumps(core.check_setup(), indent=2))
        return 0
    if argv and argv[0] in ("-h", "--help"):
        print("miragea-mcp: MCP server (stdio) for Miragea voiceover and captions.\n"
              "  miragea-mcp            run the server (configure it in your MCP client)\n"
              "  miragea-mcp --check    check key, ffmpeg and voices\n"
              "Env: MIRAGEA_API_KEY (required), MIRAGEA_VOICE_ID, MIRAGEA_REF_URL, MIRAGEA_REF_TEXT, MIRAGEA_OUTPUT_DIR")
        return 0
    build_server().run()
    return 0
