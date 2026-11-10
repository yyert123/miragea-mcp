# Miragea MCP: voiceover, voice cloning and captions for Claude, Cursor and Codex

<!-- mcp-name: io.github.yyert123/miragea-mcp -->

An MCP server that gives your AI agent a real voice toolkit: **text of any length to speech** in your saved
or cloned voice, **exact durations** for every file, **readable SRT/VTT captions** from any local audio or
video, and **per-scene narration** with `durationInFrames` and word-level captions for Remotion and other
video timelines. Local stdio server, one line of config, no GPU. Voice and speech recognition by
[Miragea](https://miragea.ai).

```json
{
  "mcpServers": {
    "miragea": {
      "command": "uvx",
      "args": ["miragea-mcp"],
      "env": { "MIRAGEA_API_KEY": "your_key", "MIRAGEA_VOICE_ID": "optional_default_voice" }
    }
  }
}
```

Claude Code: `claude mcp add miragea -e MIRAGEA_API_KEY=your_key -- uvx miragea-mcp`.
No uv? `pip install miragea-mcp` and use `"command": "miragea-mcp"`. Check everything with
`uvx miragea-mcp --check`.

Then just ask:

- *"Read this changelog aloud in my voice and save it as release-notes.mp3."*
- *"Make captions for ~/Videos/talk.mp4."* / *"TikTok-style captions for clip.mov."*
- *"Narrate these 5 scenes for my Remotion video and set each scene's durationInFrames."*

## Tools

| Tool | What it does | Returns |
|---|---|---|
| `check_setup` | Checks key, ffmpeg, saved voices, output folder; gives a fix for each problem | status + problems |
| `list_voices` | Voices saved in your Miragea account | `voice_id`, `name` |
| `speak` | Any length of text to speech (split at sentence ends under the 2,000-char API limit, joined back seamlessly). Saved voice, or clone from a public clip | file path, **exact seconds**, chunks |
| `transcribe` | Local audio/video to SRT + VTT: whole words (no mid-word splits), 2 x 42-char lines, min/max cue time; `style="shorts"` for 1-3 word uppercase captions | srt/vtt paths, text, language |
| `narrate_scenes` | One audio file per scene, `seconds`, `durationInFrames` (rounded up, never cut off), `startFrame`, a `narration.json` manifest; `captions=true` adds word-level `captions.json` in Remotion's `Caption` shape | manifest |

## What it does for you automatically

- **Long text**: chunked at sentence boundaries and stitched with a natural 120 ms pause. You never see
  the 2,000-character limit.
- **Durations**: measured from the audio itself, so video timelines line up to the frame.
- **Captions**: speech-recognition segments are rebuilt into whole words and re-flowed with broadcast rules.
- **Uploads**: video files are reduced to a 16 kHz mono track before upload (fast, small).
- **Caching**: the same text, voice and model is never billed twice; the same file is never transcribed twice.
- **Safety**: existing files are never overwritten (`name-2.mp3`), the key is only read from the environment
  and never logged, failed audio tasks are refunded by Miragea, and network retries reuse the same
  idempotency key so a retry cannot double-charge.
- **Clear errors**: every error comes back as `{"error", "how_to_fix"}` for the agent to act on.

## Compared with other voice MCP servers

| | **miragea-mcp** | ElevenLabs MCP | Thin TTS wrappers (Edge, Kokoro, Azure...) |
|---|---|---|---|
| Local stdio server, maintained | Yes | Local server deprecated; hosted OAuth server instead | Varies |
| Reads/writes files anywhere you point it | Yes (default `~/Miragea`) | Local version restricted inputs to one base folder | Usually output folder only |
| Returns exact audio duration | Yes, every call | No (callers had to measure it) | Rarely |
| Text longer than one API request | Automatic split and join | Manual | Varies |
| Captions (SRT/VTT) from local files | Yes, reflowed whole words | Separate speech-to-text tool | No |
| Scene durations in frames + Remotion captions | Yes (`narrate_scenes`) | No | No |
| Your own cloned voice | Saved voice id or reference clip | Yes (paid plans) | Stock voices only |
| Billing | Pay-as-you-go Miragea points | Subscription credits | Free / cloud account |

Sources: ElevenLabs MCP [README](https://github.com/elevenlabs/elevenlabs-mcp) (deprecation notice) and the
[remotion-superpowers changelog](https://github.com/DojoCodingLabs/remotion-superpowers/blob/main/CHANGELOG.md)
(base-folder restriction, no duration returned).

## Configuration

| Env var | Required | Meaning |
|---|---|---|
| `MIRAGEA_API_KEY` | yes | Your key from [miragea.ai](https://miragea.ai) |
| `MIRAGEA_VOICE_ID` | no | Default saved voice, so the agent never has to ask |
| `MIRAGEA_REF_URL`, `MIRAGEA_REF_TEXT` | no | Default reference clip (public URL) and its exact words |
| `MIRAGEA_OUTPUT_DIR` | no | Where files go when no path is given (default `~/Miragea`) |

Requirements: Python 3.10+. ffmpeg is optional (without it audio is saved as WAV and videos are uploaded whole).

## FAQ

**Which MCP clients work?** Any stdio MCP client: Claude Desktop, Claude Code, Cursor, Windsurf, VS Code
(Copilot agent mode), Codex CLI, Gemini CLI, Cline, Zed.

**How do I use my own voice?** Save your voice once in your Miragea account and set `MIRAGEA_VOICE_ID`, or
pass `reference_audio_url` (a public link to a clean 5-20 s clip) with `reference_text` (its exact words,
which uses the cheaper 1x rate). A direct upload of local reference clips is planned by Miragea; until then
the reference must be a public URL.

**What does it cost?** Speech is billed per character, captions at 3 points per audio second (live rates:
`GET https://miragea.ai/v1/capabilities`). Cached repeats are free.

**Is my key safe?** It is read from the server's environment only, never written to disk, logged or returned.

**Can I clone anyone's voice?** No. Only clone your own voice or one you have permission to use.

**Where are files saved?** Where you ask, or in `MIRAGEA_OUTPUT_DIR` (default `~/Miragea`). The cache lives in
`~/Miragea/.cache` and can be deleted at any time.

## Related

- [miragea-skills](https://github.com/yyert123/miragea-skills): Agent Skills for screen-recording voiceover, Shorts, captions and Remotion narration.
- [Retake](https://github.com/yyert123/retake): fix a flubbed voiceover line in your own voice (CLI + MCP).
- [HeadVox](https://github.com/yyert123/headvox): script to voiceover with word-aligned captions.

MIT License.
