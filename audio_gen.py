#!/usr/bin/env python3
"""
March Madness Agent Swarm — Audio Generator
Converts debate transcripts into podcast-style audio using the ElevenLabs API.

Usage:
    python audio_gen.py debates/R64_Duke_vs_American.md
    python audio_gen.py --all
    python audio_gen.py --all --dry-run
"""

import argparse
import io
import os
import re
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# ElevenLabs configuration
# ---------------------------------------------------------------------------
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
ELEVENLABS_TTS_URL = f"{ELEVENLABS_BASE_URL}/v1/text-to-speech"

# Default premade voice IDs from ElevenLabs
# These are the built-in voices available on all accounts.
VOICE_MAP = {
    "Tempo Hawk": {
        "voice_id": "pNInz6obpgDQGcFmaJgB",   # Adam — deep, analytical
        "style": "fast-paced, analytical",
        "stability": 0.4,
        "similarity_boost": 0.8,
        "style_exaggeration": 0.3,
    },
    "Iron Curtain": {
        "voice_id": "ErXwobaYiN019PkySvjV",   # Antoni — gruff, intense
        "style": "gruff, intense",
        "stability": 0.6,
        "similarity_boost": 0.75,
        "style_exaggeration": 0.2,
    },
    "Glass Cannon": {
        "voice_id": "TxGEqnHWrfWFTfGW9XjX",   # Josh — energetic, excited
        "style": "energetic, excited",
        "stability": 0.3,
        "similarity_boost": 0.85,
        "style_exaggeration": 0.4,
    },
    "Road Dog": {
        "voice_id": "VR6AewLTigWG4xSOukaG",   # Arnold — slow, gravelly, wise
        "style": "slow, gravelly, wise",
        "stability": 0.7,
        "similarity_boost": 0.7,
        "style_exaggeration": 0.15,
    },
    "Whisper": {
        "voice_id": "AZnzlk1XvdvUeBnXmlld",   # Domi — quiet, conspiratorial
        "style": "quiet, conspiratorial",
        "stability": 0.5,
        "similarity_boost": 0.9,
        "style_exaggeration": 0.35,
    },
    "Oracle": {
        "voice_id": "onwK4e9ZLuTAKqWW03F9",   # Daniel — measured, professorial
        "style": "measured, professorial",
        "stability": 0.65,
        "similarity_boost": 0.8,
        "style_exaggeration": 0.1,
    },
    "The Conductor": {
        "voice_id": "2EiwWnXFnvU5JabPnv8n",   # Clyde — authoritative, commanding
        "style": "authoritative, commanding",
        "stability": 0.55,
        "similarity_boost": 0.85,
        "style_exaggeration": 0.25,
    },
}

# Narrator uses Adam voice with calm settings
NARRATOR_VOICE = {
    "voice_id": "pNInz6obpgDQGcFmaJgB",  # Adam
    "stability": 0.7,
    "similarity_boost": 0.75,
    "style_exaggeration": 0.0,
}

# ---------------------------------------------------------------------------
# Parsed debate structures
# ---------------------------------------------------------------------------

@dataclass
class AgentSegment:
    agent_name: str
    quote: str
    pick: str
    confidence: int
    key_stat: str


@dataclass
class ConductorSegment:
    quote: str
    pick: str
    confidence: int
    key_factor: str
    most_weighted: str
    dissent: str


@dataclass
class ParsedDebate:
    round_label: str       # e.g. "R64"
    region: str            # e.g. "East Region"
    seed_a: str
    team_a: str
    seed_b: str
    team_b: str
    timestamp: str
    agents: list[AgentSegment] = field(default_factory=list)
    conductor: ConductorSegment | None = None
    vote_tally: str = ""


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def parse_debate_markdown(filepath: Path) -> ParsedDebate:
    """Parse a debate .md file back into structured data."""
    text = filepath.read_text(encoding="utf-8")
    lines = text.strip().split("\n")

    # Line 1: "# R64 — East Region"
    header_match = re.match(r"^#\s+(\S+)\s+[—-]\s+(.+)$", lines[0])
    round_label = header_match.group(1) if header_match else ""
    region = header_match.group(2).strip() if header_match else ""

    # Line 2: "## #1 Duke vs #16 American"
    matchup_match = re.match(r"^##\s+#(\d+)\s+(.+?)\s+vs\s+#(\d+)\s+(.+)$", lines[1])
    seed_a = matchup_match.group(1) if matchup_match else ""
    team_a = matchup_match.group(2).strip() if matchup_match else ""
    seed_b = matchup_match.group(3) if matchup_match else ""
    team_b = matchup_match.group(4).strip() if matchup_match else ""

    # Line 3: timestamp
    ts_match = re.match(r"^\*(.+)\*$", lines[2])
    timestamp = ts_match.group(1) if ts_match else ""

    debate = ParsedDebate(
        round_label=round_label,
        region=region,
        seed_a=seed_a,
        team_a=team_a,
        seed_b=seed_b,
        team_b=team_b,
        timestamp=timestamp,
    )

    # Parse agent segments — look for emoji + **AGENT NAME**: "quote" pattern
    # Agent lines: emoji **AGENT_NAME**: "quote"
    # Pick lines:    *Pick: **Team** (NN%) | Key stat: ...*
    agent_pattern = re.compile(
        r'^\S+\s+\*\*([A-Z ]+)\*\*:\s+"(.+)"$'
    )
    pick_pattern = re.compile(
        r'^\s+\*Pick:\s+\*\*(.+?)\*\*\s+\((\d+)%\)\s+\|\s+Key stat:\s+(.+)\*$'
    )

    # Conductor quote
    conductor_pattern = re.compile(
        r'^\S+\s+\*\*THE CONDUCTOR\*\*:\s+"(.+)"$'
    )
    conductor_pick_pattern = re.compile(
        r'^\s+\*\*PICK:\s+(.+?)\s+\((\d+)%\)\*\*$'
    )

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for agent segment (not conductor)
        m = agent_pattern.match(line)
        if m and m.group(1) != "THE CONDUCTOR":
            agent_name_raw = m.group(1)
            quote = m.group(2)
            # Title-case the agent name
            agent_name = agent_name_raw.title()

            # Next non-blank line should be the pick line
            j = i + 1
            pick = ""
            confidence = 0
            key_stat = ""
            while j < len(lines):
                pm = pick_pattern.match(lines[j])
                if pm:
                    pick = pm.group(1)
                    confidence = int(pm.group(2))
                    key_stat = pm.group(3)
                    break
                if lines[j].strip() and not lines[j].startswith("   "):
                    break
                j += 1

            debate.agents.append(AgentSegment(
                agent_name=agent_name,
                quote=quote,
                pick=pick,
                confidence=confidence,
                key_stat=key_stat,
            ))
            i = j + 1
            continue

        # Check for conductor
        cm = conductor_pattern.match(line)
        if cm:
            conductor_quote = cm.group(1)
            cpick = ""
            cconf = 0
            key_factor = ""
            most_weighted = ""
            dissent = ""
            j = i + 1
            while j < len(lines):
                cpm = conductor_pick_pattern.match(lines[j])
                if cpm:
                    cpick = cpm.group(1)
                    cconf = int(cpm.group(2))
                kf = re.match(r'^\s+\*Key factor:\s+(.+)\*$', lines[j])
                if kf:
                    key_factor = kf.group(1)
                mw = re.match(r'^\s+\*Most weighted:\s+(.+)\*$', lines[j])
                if mw:
                    most_weighted = mw.group(1)
                dr = re.match(r'^\s+\*Dissent report:\s+(.+)\*$', lines[j])
                if dr:
                    dissent = dr.group(1)
                if lines[j].startswith("---"):
                    break
                j += 1

            debate.conductor = ConductorSegment(
                quote=conductor_quote,
                pick=cpick,
                confidence=cconf,
                key_factor=key_factor,
                most_weighted=most_weighted,
                dissent=dissent,
            )
            i = j + 1
            continue

        # Vote tally section
        if line.strip() == "### Vote Tally":
            tally_lines = []
            j = i + 1
            while j < len(lines):
                if lines[j].strip().startswith("- **"):
                    tally_lines.append(lines[j].strip())
                j += 1
            debate.vote_tally = " ".join(tally_lines)
            i = j
            continue

        i += 1

    return debate


# ---------------------------------------------------------------------------
# Audio generation helpers
# ---------------------------------------------------------------------------

def generate_silence_mp3(duration_seconds: float) -> bytes:
    """Generate a short silence as valid MP3 data.

    Creates a minimal MP3 frame sequence representing silence.
    For simplicity we produce a WAV-style silence and rely on
    ElevenLabs returning MP3; this silence is raw bytes that
    ffmpeg or most players handle when concatenated with MP3.

    Actually, we'll produce a proper minimal MP3 silence by
    writing MPEG1 Layer3 frames of zero-audio.
    """
    # A single silent MP3 frame (MPEG1, Layer 3, 128kbps, 44100Hz, stereo)
    # Frame header: 0xFFFB9004 — sync, MPEG1, Layer3, 128kbps, 44100, stereo
    # Frame size = 144 * 128000 / 44100 = 417 bytes (padded)
    frame_size = 417
    header = b'\xff\xfb\x90\x04'
    silent_frame = header + b'\x00' * (frame_size - len(header))

    # ~26 frames per second at this bitrate/samplerate
    frames_needed = int(26 * duration_seconds)
    if frames_needed < 1:
        frames_needed = 1

    return silent_frame * frames_needed


def build_speech_text(debate: ParsedDebate) -> list[tuple[str, str]]:
    """Build a list of (speaker_key, text) segments for the debate.

    speaker_key is either an agent name from VOICE_MAP, or "narrator".
    """
    segments: list[tuple[str, str]] = []

    matchup = f"number {debate.seed_a} {debate.team_a} versus number {debate.seed_b} {debate.team_b}"

    # Intro (narrator)
    intro = (
        f"Welcome to the March Madness Agent Swarm. "
        f"Today's debate: {matchup}. "
        f"{debate.round_label}, {debate.region}. "
        f"Let's hear from the panel."
    )
    segments.append(("narrator", intro))

    # Each agent speaks
    for agent in debate.agents:
        text = agent.quote
        if agent.pick and agent.confidence:
            text += f" My pick: {agent.pick}, {agent.confidence} percent confidence."
        segments.append((agent.agent_name, text))

    # Conductor verdict
    if debate.conductor:
        c = debate.conductor
        text = c.quote
        if c.pick and c.confidence:
            text += f" The final pick is {c.pick} at {c.confidence} percent."
        if c.key_factor:
            text += f" Key factor: {c.key_factor}."
        segments.append(("The Conductor", text))

    # Outro with vote tally (narrator)
    if debate.vote_tally:
        # Clean up markdown from vote tally
        tally_clean = debate.vote_tally.replace("**", "").replace("- ", "")
        outro = f"And that's the verdict. Vote tally: {tally_clean}. This has been the March Madness Agent Swarm."
    else:
        outro = "And that's the verdict. This has been the March Madness Agent Swarm."
    segments.append(("narrator", outro))

    return segments


def estimate_characters(segments: list[tuple[str, str]]) -> int:
    """Return total character count for all speech segments."""
    return sum(len(text) for _, text in segments)


# ---------------------------------------------------------------------------
# ElevenLabs TTS client
# ---------------------------------------------------------------------------

class ElevenLabsTTS:
    """Synchronous ElevenLabs TTS client using httpx."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.Client(
            timeout=60.0,
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
            },
        )

    def synthesize(self, text: str, voice_id: str,
                   stability: float = 0.5,
                   similarity_boost: float = 0.75,
                   style_exaggeration: float = 0.0) -> bytes:
        """Convert text to speech, returning MP3 bytes.

        Includes retry logic for rate limits (HTTP 429).
        """
        url = f"{ELEVENLABS_TTS_URL}/{voice_id}"
        payload = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style_exaggeration,
            },
        }

        max_retries = 3
        for attempt in range(max_retries):
            resp = self.client.post(url, json=payload)
            if resp.status_code == 200:
                return resp.content
            elif resp.status_code == 429:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                print(f"  Rate limited. Retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                resp.raise_for_status()

        raise RuntimeError(f"Failed after {max_retries} retries (rate limited)")

    def close(self):
        self.client.close()


def generate_audio_for_debate(debate: ParsedDebate, output_path: Path,
                              tts: ElevenLabsTTS) -> None:
    """Generate a single MP3 file from a parsed debate."""
    segments = build_speech_text(debate)
    silence = generate_silence_mp3(0.5)

    audio_chunks: list[bytes] = []
    total = len(segments)

    for idx, (speaker, text) in enumerate(segments, 1):
        if speaker == "narrator":
            voice_cfg = NARRATOR_VOICE
        elif speaker in VOICE_MAP:
            voice_cfg = VOICE_MAP[speaker]
        else:
            # Fallback to narrator voice
            print(f"  Warning: unknown speaker '{speaker}', using narrator voice")
            voice_cfg = NARRATOR_VOICE

        print(f"  [{idx}/{total}] Generating: {speaker} ({len(text)} chars)")
        audio = tts.synthesize(
            text=text,
            voice_id=voice_cfg["voice_id"],
            stability=voice_cfg.get("stability", 0.5),
            similarity_boost=voice_cfg.get("similarity_boost", 0.75),
            style_exaggeration=voice_cfg.get("style_exaggeration", 0.0),
        )
        audio_chunks.append(audio)

        # Add silence between speakers (not after the last one)
        if idx < total:
            audio_chunks.append(silence)

    # Concatenate all MP3 chunks
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in audio_chunks:
            f.write(chunk)

    total_bytes = sum(len(c) for c in audio_chunks)
    print(f"  Saved: {output_path} ({total_bytes / 1024:.1f} KB)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def get_output_path(debate_file: Path, output_dir: Path) -> Path:
    """Derive output MP3 path from the debate markdown filename."""
    stem = debate_file.stem  # e.g. "R64_Duke_vs_American"
    return output_dir / f"{stem}.mp3"


def print_dry_run(debate: ParsedDebate, debate_file: Path) -> None:
    """Print what would be generated without calling the API."""
    segments = build_speech_text(debate)
    total_chars = estimate_characters(segments)

    print(f"\n{'='*60}")
    print(f"Debate: {debate.team_a} vs {debate.team_b} ({debate.round_label}, {debate.region})")
    print(f"Source: {debate_file}")
    print(f"{'='*60}")
    print(f"Segments: {len(segments)}")
    for speaker, text in segments:
        voice_label = speaker
        if speaker in VOICE_MAP:
            voice_label = f"{speaker} ({VOICE_MAP[speaker]['style']})"
        elif speaker == "narrator":
            voice_label = "Narrator (Adam)"
        print(f"  - {voice_label}: {len(text)} chars")
        # Show first 80 chars of text
        preview = text[:80] + ("..." if len(text) > 80 else "")
        print(f"    \"{preview}\"")
    print(f"\nTotal characters: {total_chars:,}")
    print(f"Estimated cost: ~${total_chars * 0.00003:.4f} (at $0.30/1K chars, Starter plan)")


def main():
    parser = argparse.ArgumentParser(
        description="Convert March Madness debate transcripts to podcast-style audio via ElevenLabs."
    )
    parser.add_argument(
        "file", nargs="?", type=Path,
        help="Path to a single debate .md file",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Generate audio for all debates in the debates/ directory",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print estimated character counts without generating audio",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(__file__).parent / "audio",
        help="Output directory for MP3 files (default: audio/)",
    )
    parser.add_argument(
        "--debates-dir", type=Path,
        default=Path(__file__).parent / "debates",
        help="Directory containing debate .md files (default: debates/)",
    )
    args = parser.parse_args()

    if not args.file and not args.all:
        parser.print_help()
        sys.exit(1)

    # Collect debate files
    if args.all:
        debate_files = sorted(args.debates_dir.glob("*.md"))
        if not debate_files:
            print(f"No .md files found in {args.debates_dir}")
            sys.exit(1)
        print(f"Found {len(debate_files)} debate file(s) in {args.debates_dir}")
    else:
        if not args.file.exists():
            print(f"File not found: {args.file}")
            sys.exit(1)
        debate_files = [args.file]

    # Parse all debates first
    debates: list[tuple[Path, ParsedDebate]] = []
    for f in debate_files:
        try:
            debate = parse_debate_markdown(f)
            debates.append((f, debate))
        except Exception as e:
            print(f"Error parsing {f}: {e}")
            continue

    # Dry run mode
    if args.dry_run:
        grand_total_chars = 0
        for debate_file, debate in debates:
            print_dry_run(debate, debate_file)
            segments = build_speech_text(debate)
            grand_total_chars += estimate_characters(segments)

        if len(debates) > 1:
            print(f"\n{'='*60}")
            print(f"GRAND TOTAL: {grand_total_chars:,} characters across {len(debates)} debates")
            print(f"Estimated total cost: ~${grand_total_chars * 0.00003:.4f}")
        return

    # Check API key
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key or api_key == "el-xxxxx":
        print("="*60)
        print("ELEVENLABS_API_KEY not configured!")
        print()
        print("To generate audio, you need an ElevenLabs API key.")
        print("1. Sign up at https://elevenlabs.io")
        print("2. Go to Profile > API Key")
        print("3. Add to your .env file:")
        print()
        print("   ELEVENLABS_API_KEY=your-api-key-here")
        print()
        print("The Starter plan ($5/mo) includes 30,000 characters/month.")
        print("Use --dry-run to estimate character usage before generating.")
        print("="*60)
        sys.exit(1)

    # Show cost estimate and confirm
    grand_total_chars = 0
    for _, debate in debates:
        segments = build_speech_text(debate)
        grand_total_chars += estimate_characters(segments)

    print(f"\nTotal characters to synthesize: {grand_total_chars:,}")
    print(f"Estimated cost: ~${grand_total_chars * 0.00003:.4f}")
    print()

    # Generate audio
    tts = ElevenLabsTTS(api_key)
    try:
        for debate_file, debate in debates:
            output_path = get_output_path(debate_file, args.output_dir)
            print(f"\nGenerating: {debate.team_a} vs {debate.team_b} -> {output_path}")
            generate_audio_for_debate(debate, output_path, tts)
    finally:
        tts.close()

    print(f"\nDone! Generated {len(debates)} audio file(s) in {args.output_dir}/")


if __name__ == "__main__":
    main()
