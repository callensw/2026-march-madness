#!/usr/bin/env python3
"""
March Madness Agent Swarm — Video Generator
Creates short-form debate videos (1080x1920 vertical) showing AI agents
arguing about March Madness games, styled like a sports debate show.

Usage:
    python video_gen.py --debate debates/R64_Duke_vs_American.md
    python video_gen.py --debate debates/R64_Duke_vs_American.md --dry-run
    python video_gen.py --debate debates/R64_Duke_vs_American.md --preview
    python video_gen.py --debate debates/R64_Duke_vs_American.md --no-audio
    python video_gen.py --round R64
    python video_gen.py --debate debates/R64_Duke_vs_American.md --audio-only
"""

import argparse
import fcntl
import json
import logging
import math
import os
import re
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).parent
FONTS_DIR = PROJECT_DIR / "video_assets" / "fonts"
VIDEOS_DIR = PROJECT_DIR / "videos"
DEBATES_DIR = PROJECT_DIR / "debates"

# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------
def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a font, falling back to DejaVu then default."""
    candidates = [
        FONTS_DIR / name,
        Path("/usr/share/fonts/truetype/dejavu") / name.replace("JetBrainsMono", "DejaVuSans"),
    ]
    for p in candidates:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    # Fallback
    fallbacks = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fb in fallbacks:
        if Path(fb).exists():
            return ImageFont.truetype(fb, size)
    return ImageFont.load_default()


FONT_BOLD_LG = lambda s=48: _load_font("JetBrainsMono-Bold.ttf", s)
FONT_BOLD_MD = lambda s=36: _load_font("JetBrainsMono-Bold.ttf", s)
FONT_BOLD_SM = lambda s=28: _load_font("JetBrainsMono-Bold.ttf", s)
FONT_REG_MD = lambda s=32: _load_font("JetBrainsMono-Regular.ttf", s)
FONT_REG_SM = lambda s=26: _load_font("JetBrainsMono-Regular.ttf", s)
FONT_MED_MD = lambda s=32: _load_font("JetBrainsMono-Medium.ttf", s)

# ---------------------------------------------------------------------------
# Video dimensions
# ---------------------------------------------------------------------------
WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Preview mode uses half resolution
PREVIEW_SCALE = 0.5

# Colors
BG_COLOR = (10, 10, 15)
CARD_BG = (20, 22, 30)
CARD_BORDER = (40, 44, 55)
TITLE_GRADIENT_TOP = (15, 25, 60)
TITLE_GRADIENT_BOT = (10, 10, 15)
WHITE = (255, 255, 255)
LIGHT_GRAY = (180, 185, 195)
DIM_GRAY = (100, 105, 115)
GOLD = (245, 158, 11)
RED_ALERT = (239, 68, 68)
GREEN_CHECK = (34, 197, 94)

# ---------------------------------------------------------------------------
# Agent configuration (matching dashboard/agents.js)
# ---------------------------------------------------------------------------
AGENT_VOICES = {
    "Tempo Hawk": {
        "voice_id": "pNInz6obpgDQGcFmaJgB",  # Adam — deep, analytical
        "voice_name": "Adam",
        "emoji": "\U0001f985",
        "color": (59, 130, 246),
        "role": "Pace & Efficiency",
        "stability": 0.4,
        "similarity_boost": 0.8,
    },
    "Iron Curtain": {
        "voice_id": "ErXwobaYiN019PkySvjV",  # Antoni — gruff, intense
        "voice_name": "Antoni",
        "emoji": "\U0001f6e1\ufe0f",
        "color": (107, 114, 128),
        "role": "Defensive Specialist",
        "stability": 0.6,
        "similarity_boost": 0.75,
    },
    "Glass Cannon": {
        "voice_id": "TxGEqnHWrfWFTfGW9XjX",  # Josh — energetic, excited
        "voice_name": "Josh",
        "emoji": "\U0001f4a5",
        "color": (239, 68, 68),
        "role": "Offensive Firepower",
        "stability": 0.3,
        "similarity_boost": 0.85,
    },
    "Road Dog": {
        "voice_id": "VR6AewLTigWG4xSOukaG",  # Arnold — slow, gravelly, wise
        "voice_name": "Arnold",
        "emoji": "\U0001f43a",
        "color": (161, 98, 7),
        "role": "Experience & Intangibles",
        "stability": 0.7,
        "similarity_boost": 0.7,
    },
    "Whisper": {
        "voice_id": "AZnzlk1XvdvUeBnXmlld",  # Domi — quiet, conspiratorial
        "voice_name": "Domi",
        "emoji": "\U0001f441\ufe0f",
        "color": (139, 92, 246),
        "role": "Sentiment & Injury Intel",
        "stability": 0.5,
        "similarity_boost": 0.9,
    },
    "Oracle": {
        "voice_id": "onwK4e9ZLuTAKqWW03F9",  # Daniel — measured, professorial
        "voice_name": "Daniel",
        "emoji": "\U0001f4dc",
        "color": (5, 150, 105),
        "role": "Historical Patterns",
        "stability": 0.65,
        "similarity_boost": 0.8,
    },
    "Streak": {
        "voice_id": "VR6AewLTigWG4xSOukaG",  # Arnold
        "voice_name": "Arnold",
        "emoji": "\U0001f525",
        "color": (255, 107, 53),
        "role": "Momentum & Form",
        "stability": 0.35,
        "similarity_boost": 0.85,
    },
    "The Conductor": {
        "voice_id": "2EiwWnXFnvU5JabPnv8n",  # Clyde — authoritative, commanding
        "voice_name": "Clyde",
        "emoji": "\U0001f3bc",
        "color": (245, 158, 11),
        "role": "Final Decision",
        "stability": 0.55,
        "similarity_boost": 0.85,
    },
}

# Narrator voice (for intro/outro)
NARRATOR_VOICE = {
    "voice_id": "onwK4e9ZLuTAKqWW03F9",  # Daniel
    "stability": 0.7,
    "similarity_boost": 0.75,
}


# ---------------------------------------------------------------------------
# Parsed debate structures (reuse from audio_gen.py)
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
    round_label: str
    region: str
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
    """Parse a debate .md file into structured data."""
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

    ts_match = re.match(r"^\*(.+)\*$", lines[2])
    timestamp = ts_match.group(1) if ts_match else ""

    debate = ParsedDebate(
        round_label=round_label, region=region,
        seed_a=seed_a, team_a=team_a, seed_b=seed_b, team_b=team_b,
        timestamp=timestamp,
    )

    agent_pattern = re.compile(r'^\S+\s+\*\*([A-Z ]+)\*\*(?:\s*`\[.*?\]`)?\s*:\s+"(.+)"$')
    pick_pattern = re.compile(
        r'^\s+\*Pick:\s+\*\*(.+?)\*\*\s+\((\d+)%\)\s+\|\s+Key stat:\s+(.+)\*$'
    )
    conductor_pattern = re.compile(r'^\S+\s+\*\*THE CONDUCTOR\*\*:\s+"(.+)"$')
    conductor_pick_pattern = re.compile(r'^\s+\*\*PICK:\s+(.+?)\s+\((\d+)%\)\*\*$')

    i = 0
    while i < len(lines):
        line = lines[i]

        m = agent_pattern.match(line)
        if m and m.group(1) != "THE CONDUCTOR":
            agent_name = m.group(1).title()
            quote = m.group(2)
            j = i + 1
            pick, confidence, key_stat = "", 0, ""
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
            debate.agents.append(AgentSegment(agent_name, quote, pick, confidence, key_stat))
            i = j + 1
            continue

        cm = conductor_pattern.match(line)
        if cm:
            conductor_quote = cm.group(1)
            cpick, cconf = "", 0
            key_factor, most_weighted, dissent = "", "", ""
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
                conductor_quote, cpick, cconf, key_factor, most_weighted, dissent)
            i = j + 1
            continue

        if line.strip() == "### Vote Tally":
            tally_lines = []
            j = i + 1
            while j < len(lines):
                if lines[j].strip().startswith("- **"):
                    tally_lines.append(lines[j].strip())
                j += 1
            debate.vote_tally = "\n".join(tally_lines)
            i = j
            continue

        i += 1

    return debate


def validate_parsed_debate(debate: ParsedDebate) -> list[str]:
    """Validate that a parsed debate has the required fields.

    Returns a list of error strings. An empty list means valid.
    """
    errors = []
    if not debate.team_a or not debate.team_b:
        errors.append("Missing team names (team_a or team_b is empty)")
    if not debate.round_label:
        errors.append("Missing round label")
    if not debate.region:
        errors.append("Missing region")
    if not debate.seed_a or not debate.seed_b:
        errors.append("Missing seed numbers")
    if not debate.agents:
        errors.append("No agent segments found in debate")
    if not debate.conductor:
        errors.append("No conductor segment found in debate")
    return errors


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _darken(color: tuple, factor: float = 0.3) -> tuple:
    return tuple(max(0, int(c * factor)) for c in color)


def _lighten(color: tuple, factor: float = 1.5) -> tuple:
    return tuple(min(255, int(c * factor)) for c in color)


def draw_rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int,
                      fill=None, outline=None, width: int = 1):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = font.getbbox(test)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def get_text_height(text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = font.getbbox(text)
    return bbox[3] - bbox[1]


# ---------------------------------------------------------------------------
# Frame renderers
# ---------------------------------------------------------------------------
class FrameRenderer:
    """Renders individual frames for the video as PIL Images."""

    def __init__(self, debate: ParsedDebate, scale: float = 1.0):
        self.debate = debate
        self.scale = scale
        self.w = int(WIDTH * scale)
        self.h = int(HEIGHT * scale)
        # Pre-load fonts at scaled sizes
        self._fonts = {}

    def font(self, style: str, base_size: int) -> ImageFont.FreeTypeFont:
        key = (style, base_size)
        if key not in self._fonts:
            size = max(12, int(base_size * self.scale))
            name_map = {
                "bold": "JetBrainsMono-Bold.ttf",
                "medium": "JetBrainsMono-Medium.ttf",
                "regular": "JetBrainsMono-Regular.ttf",
            }
            self._fonts[key] = _load_font(name_map.get(style, "JetBrainsMono-Regular.ttf"), size)
        return self._fonts[key]

    def s(self, val: int) -> int:
        """Scale a pixel value."""
        return max(1, int(val * self.scale))

    def _base_frame(self) -> Image.Image:
        """Create a blank dark background frame."""
        return Image.new("RGB", (self.w, self.h), BG_COLOR)

    def _draw_title_bar(self, draw: ImageDraw.Draw):
        """Draw the title bar at the top."""
        # Gradient background
        for y in range(self.s(140)):
            t = y / self.s(140)
            r = int(TITLE_GRADIENT_TOP[0] * (1-t) + TITLE_GRADIENT_BOT[0] * t)
            g = int(TITLE_GRADIENT_TOP[1] * (1-t) + TITLE_GRADIENT_BOT[1] * t)
            b = int(TITLE_GRADIENT_TOP[2] * (1-t) + TITLE_GRADIENT_BOT[2] * t)
            draw.line([(0, y), (self.w, y)], fill=(r, g, b))

        # Title text
        f_title = self.font("bold", 42)
        f_sub = self.font("medium", 28)
        draw.text((self.w // 2, self.s(40)), "MARCH MADNESS 2026",
                  fill=WHITE, font=f_title, anchor="mt")
        draw.text((self.w // 2, self.s(90)), "AGENT SWARM DEBATE",
                  fill=GOLD, font=f_sub, anchor="mt")

        # Bottom line
        draw.line([(self.s(40), self.s(135)), (self.w - self.s(40), self.s(135))],
                  fill=GOLD, width=self.s(2))

    def _draw_matchup_card(self, draw: ImageDraw.Draw, y_start: int) -> int:
        """Draw the matchup card. Returns y position after card."""
        d = self.debate
        pad = self.s(40)
        card_h = self.s(120)
        margin = self.s(30)

        draw_rounded_rect(draw,
            (pad, y_start, self.w - pad, y_start + card_h),
            radius=self.s(16), fill=CARD_BG, outline=CARD_BORDER, width=self.s(2))

        f_matchup = self.font("bold", 38)
        f_detail = self.font("regular", 24)

        matchup_text = f"#{d.seed_a} {d.team_a.upper()} vs #{d.seed_b} {d.team_b.upper()}"
        draw.text((self.w // 2, y_start + self.s(35)),
                  matchup_text, fill=WHITE, font=f_matchup, anchor="mt")

        detail = f"{d.region.upper()}  \u2022  {d.round_label}"
        draw.text((self.w // 2, y_start + self.s(80)),
                  detail, fill=DIM_GRAY, font=f_detail, anchor="mt")

        return y_start + card_h + margin

    def render_intro(self, progress: float = 1.0) -> Image.Image:
        """Render the intro/title frame with optional fade-in."""
        img = self._base_frame()
        draw = ImageDraw.Draw(img)
        self._draw_title_bar(draw)

        # Big matchup in center
        d = self.debate
        f_vs = self.font("bold", 64)
        f_team = self.font("bold", 52)
        f_seed = self.font("medium", 36)
        f_detail = self.font("regular", 28)

        cy = self.h // 2 - self.s(80)

        # Team A
        draw.text((self.w // 2, cy - self.s(80)),
                  f"#{d.seed_a}", fill=DIM_GRAY, font=f_seed, anchor="mt")
        draw.text((self.w // 2, cy - self.s(40)),
                  d.team_a.upper(), fill=WHITE, font=f_team, anchor="mt")

        # VS
        draw.text((self.w // 2, cy + self.s(30)),
                  "VS", fill=GOLD, font=f_vs, anchor="mm")

        # Team B
        draw.text((self.w // 2, cy + self.s(100)),
                  d.team_b.upper(), fill=WHITE, font=f_team, anchor="mt")
        draw.text((self.w // 2, cy + self.s(160)),
                  f"#{d.seed_b}", fill=DIM_GRAY, font=f_seed, anchor="mt")

        # Region + Round
        draw.text((self.w // 2, cy + self.s(230)),
                  f"{d.region}  \u2022  {d.round_label}",
                  fill=LIGHT_GRAY, font=f_detail, anchor="mt")

        # "WHO WINS?" text at bottom
        f_cta = self.font("bold", 36)
        draw.text((self.w // 2, self.h - self.s(200)),
                  "WHO WINS?", fill=GOLD, font=f_cta, anchor="mt")

        # Apply fade
        if progress < 1.0:
            alpha = int(255 * progress)
            overlay = Image.new("RGB", (self.w, self.h), BG_COLOR)
            img = Image.blend(overlay, img, progress)

        return img

    def render_agent_card(self, agent: AgentSegment, text_progress: float = 1.0,
                          votes_so_far: list[AgentSegment] = None) -> Image.Image:
        """Render a frame showing an agent's argument."""
        img = self._base_frame()
        draw = ImageDraw.Draw(img)
        self._draw_title_bar(draw)

        # Matchup card
        y = self._draw_matchup_card(draw, self.s(155))

        # Agent info
        agent_key = agent.agent_name
        # Handle title case matching
        voice_cfg = None
        for name, cfg in AGENT_VOICES.items():
            if name.lower() == agent_key.lower():
                voice_cfg = cfg
                agent_key = name
                break
        if not voice_cfg:
            voice_cfg = {"emoji": "?", "color": (128, 128, 128), "role": "Unknown"}

        agent_color = voice_cfg["color"]
        emoji = voice_cfg.get("emoji", "?")
        role = voice_cfg.get("role", "")

        pad = self.s(40)
        card_top = y + self.s(10)

        # Agent name header bar
        header_h = self.s(70)
        draw_rounded_rect(draw,
            (pad, card_top, self.w - pad, card_top + header_h),
            radius=self.s(12),
            fill=_darken(agent_color, 0.25),
            outline=agent_color, width=self.s(3))

        f_name = self.font("bold", 34)
        f_role = self.font("regular", 22)

        # Agent name + emoji (emoji may not render in all fonts, so just use text)
        name_text = f"{agent_key.upper()}"
        draw.text((pad + self.s(20), card_top + self.s(10)),
                  name_text, fill=WHITE, font=f_name)
        # Role on right
        draw.text((self.w - pad - self.s(20), card_top + self.s(25)),
                  role, fill=_lighten(agent_color), font=f_role, anchor="rm")

        # Quote card
        quote_top = card_top + header_h + self.s(15)
        f_quote = self.font("regular", 30)
        max_text_w = self.w - pad * 2 - self.s(40)
        wrapped = wrap_text(agent.quote, f_quote, max_text_w)

        # Show lines based on text_progress
        lines_to_show = max(1, int(len(wrapped) * text_progress))
        visible_lines = wrapped[:lines_to_show]

        line_h = self.s(42)
        quote_card_h = len(wrapped) * line_h + self.s(40)
        draw_rounded_rect(draw,
            (pad, quote_top, self.w - pad, quote_top + quote_card_h),
            radius=self.s(12), fill=CARD_BG, outline=CARD_BORDER, width=self.s(1))

        # Opening quote mark
        f_quote_mark = self.font("bold", 48)
        draw.text((pad + self.s(15), quote_top + self.s(5)),
                  "\u201c", fill=_darken(agent_color, 0.6), font=f_quote_mark)

        for li, line_text in enumerate(visible_lines):
            ly = quote_top + self.s(20) + li * line_h
            draw.text((pad + self.s(25), ly), line_text, fill=LIGHT_GRAY, font=f_quote)

        # Pick badge (show when text is fully revealed)
        badge_y = quote_top + quote_card_h + self.s(20)
        if text_progress >= 0.9 and agent.pick:
            badge_w = self.s(400)
            badge_h = self.s(70)
            badge_x = (self.w - badge_w) // 2
            draw_rounded_rect(draw,
                (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
                radius=self.s(12), fill=_darken(agent_color, 0.4),
                outline=agent_color, width=self.s(2))

            f_pick = self.font("bold", 32)
            pick_text = f"PICK: {agent.pick.upper()}  {agent.confidence}%"
            draw.text((self.w // 2, badge_y + badge_h // 2),
                      pick_text, fill=WHITE, font=f_pick, anchor="mm")
            badge_y += badge_h + self.s(15)

            # Key stat
            if agent.key_stat:
                f_stat = self.font("regular", 22)
                draw.text((self.w // 2, badge_y),
                          agent.key_stat, fill=DIM_GRAY, font=f_stat, anchor="mt")

        # Vote indicators at bottom
        if votes_so_far:
            self._draw_vote_indicators(draw, votes_so_far, self.h - self.s(180))

        return img

    def render_vote_tally(self, votes: list[AgentSegment],
                          conductor: ConductorSegment = None) -> Image.Image:
        """Render the vote tally frame."""
        img = self._base_frame()
        draw = ImageDraw.Draw(img)
        self._draw_title_bar(draw)
        y = self._draw_matchup_card(draw, self.s(155))

        d = self.debate
        f_header = self.font("bold", 40)
        f_vote = self.font("bold", 32)
        f_name = self.font("regular", 28)

        y += self.s(30)
        draw.text((self.w // 2, y), "VOTE TALLY", fill=GOLD, font=f_header, anchor="mt")
        y += self.s(70)

        # Count votes
        team_a_votes = [v for v in votes if v.pick == d.team_a]
        team_b_votes = [v for v in votes if v.pick == d.team_b]

        # Team A column
        pad = self.s(60)
        col_w = (self.w - pad * 3) // 2

        # Team A
        draw.text((pad + col_w // 2, y),
                  f"{d.team_a.upper()}", fill=WHITE, font=f_vote, anchor="mt")
        draw.text((pad + col_w // 2, y + self.s(45)),
                  f"{len(team_a_votes)}", fill=GOLD, font=self.font("bold", 72), anchor="mt")
        vy = y + self.s(140)
        for v in team_a_votes:
            vname = v.agent_name
            for name, cfg in AGENT_VOICES.items():
                if name.lower() == vname.lower():
                    vname = name
                    break
            draw.text((pad + col_w // 2, vy),
                      f"{vname} ({v.confidence}%)", fill=LIGHT_GRAY, font=f_name, anchor="mt")
            vy += self.s(40)

        # Team B
        col2_x = pad * 2 + col_w
        draw.text((col2_x + col_w // 2, y),
                  f"{d.team_b.upper()}", fill=WHITE, font=f_vote, anchor="mt")
        draw.text((col2_x + col_w // 2, y + self.s(45)),
                  f"{len(team_b_votes)}", fill=GOLD, font=self.font("bold", 72), anchor="mt")
        vy = y + self.s(140)
        for v in team_b_votes:
            vname = v.agent_name
            for name, cfg in AGENT_VOICES.items():
                if name.lower() == vname.lower():
                    vname = name
                    break
            draw.text((col2_x + col_w // 2, vy),
                      f"{vname} ({v.confidence}%)", fill=LIGHT_GRAY, font=f_name, anchor="mt")
            vy += self.s(40)

        # Divider
        div_x = self.w // 2
        draw.line([(div_x, y), (div_x, y + self.s(400))], fill=CARD_BORDER, width=self.s(2))

        return img

    def render_conductor(self, text_progress: float = 1.0,
                         votes: list[AgentSegment] = None) -> Image.Image:
        """Render the Conductor's verdict frame."""
        img = self._base_frame()
        draw = ImageDraw.Draw(img)
        self._draw_title_bar(draw)
        y = self._draw_matchup_card(draw, self.s(155))

        c = self.debate.conductor
        if not c:
            return img

        pad = self.s(40)

        # "THE VERDICT" header
        f_verdict = self.font("bold", 40)
        y += self.s(20)
        draw.text((self.w // 2, y), "THE VERDICT", fill=GOLD, font=f_verdict, anchor="mt")
        y += self.s(70)

        # Conductor card with gold border
        card_top = y
        header_h = self.s(70)
        draw_rounded_rect(draw,
            (pad, card_top, self.w - pad, card_top + header_h),
            radius=self.s(12),
            fill=_darken(GOLD, 0.2),
            outline=GOLD, width=self.s(3))

        f_name = self.font("bold", 34)
        draw.text((pad + self.s(20), card_top + self.s(15)),
                  "THE CONDUCTOR", fill=WHITE, font=f_name)
        f_role = self.font("regular", 22)
        draw.text((self.w - pad - self.s(20), card_top + self.s(25)),
                  "Final Decision", fill=GOLD, font=f_role, anchor="rm")

        # Quote
        quote_top = card_top + header_h + self.s(15)
        f_quote = self.font("regular", 30)
        max_text_w = self.w - pad * 2 - self.s(40)
        wrapped = wrap_text(c.quote, f_quote, max_text_w)
        lines_to_show = max(1, int(len(wrapped) * text_progress))

        line_h = self.s(42)
        quote_h = len(wrapped) * line_h + self.s(40)
        draw_rounded_rect(draw,
            (pad, quote_top, self.w - pad, quote_top + quote_h),
            radius=self.s(12), fill=CARD_BG, outline=CARD_BORDER, width=self.s(1))

        for li, lt in enumerate(wrapped[:lines_to_show]):
            ly = quote_top + self.s(20) + li * line_h
            draw.text((pad + self.s(25), ly), lt, fill=LIGHT_GRAY, font=f_quote)

        # Pick badge
        badge_y = quote_top + quote_h + self.s(25)
        if text_progress >= 0.8 and c.pick:
            badge_w = self.s(500)
            badge_h = self.s(80)
            badge_x = (self.w - badge_w) // 2
            draw_rounded_rect(draw,
                (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
                radius=self.s(16), fill=_darken(GOLD, 0.3),
                outline=GOLD, width=self.s(3))

            f_pick = self.font("bold", 38)
            draw.text((self.w // 2, badge_y + badge_h // 2),
                      f"FINAL: {c.pick.upper()} ({c.confidence}%)",
                      fill=WHITE, font=f_pick, anchor="mm")
            badge_y += badge_h + self.s(20)

            # Key factor
            if c.key_factor:
                f_factor = self.font("regular", 24)
                draw.text((self.w // 2, badge_y),
                          f"Key factor: {c.key_factor}", fill=DIM_GRAY, font=f_factor, anchor="mt")
                badge_y += self.s(40)

            # Most weighted
            if c.most_weighted:
                f_factor = self.font("regular", 24)
                draw.text((self.w // 2, badge_y),
                          f"Most weighted: {c.most_weighted}", fill=DIM_GRAY, font=f_factor, anchor="mt")

            # Upset alert if lower seed picked
            d = self.debate
            is_upset = False
            if c.pick == d.team_b and int(d.seed_a) < int(d.seed_b):
                is_upset = True
            elif c.pick == d.team_a and int(d.seed_b) < int(d.seed_a):
                is_upset = True

            if is_upset:
                alert_y = self.h - self.s(350)
                alert_w = self.s(400)
                alert_h = self.s(60)
                alert_x = (self.w - alert_w) // 2
                draw_rounded_rect(draw,
                    (alert_x, alert_y, alert_x + alert_w, alert_y + alert_h),
                    radius=self.s(12), fill=(100, 20, 20), outline=RED_ALERT, width=self.s(3))
                f_alert = self.font("bold", 32)
                draw.text((self.w // 2, alert_y + alert_h // 2),
                          "UPSET ALERT", fill=RED_ALERT, font=f_alert, anchor="mm")

        # Vote indicators at bottom
        if votes:
            self._draw_vote_indicators(draw, votes, self.h - self.s(180))

        return img

    def render_outro(self) -> Image.Image:
        """Render the outro/branding frame."""
        img = self._base_frame()
        draw = ImageDraw.Draw(img)

        f_brand = self.font("bold", 44)
        f_sub = self.font("medium", 30)
        f_small = self.font("regular", 24)

        cy = self.h // 2
        draw.text((self.w // 2, cy - self.s(60)),
                  "MARCH MADNESS", fill=WHITE, font=f_brand, anchor="mt")
        draw.text((self.w // 2, cy),
                  "AGENT SWARM", fill=GOLD, font=f_brand, anchor="mt")
        draw.text((self.w // 2, cy + self.s(60)),
                  "2026", fill=LIGHT_GRAY, font=f_sub, anchor="mt")

        draw.text((self.w // 2, self.h - self.s(200)),
                  "7 AI agents. Every game. Who wins?",
                  fill=DIM_GRAY, font=f_small, anchor="mt")

        return img

    def _draw_vote_indicators(self, draw: ImageDraw.Draw,
                              votes: list[AgentSegment], y: int):
        """Draw small vote indicator icons at the bottom of the frame."""
        d = self.debate
        all_agent_names = ["Tempo Hawk", "Iron Curtain", "Glass Cannon",
                           "Road Dog", "Whisper", "Oracle"]
        voted = {v.agent_name.title(): v for v in votes}

        # Count
        team_a_count = sum(1 for v in votes if v.pick == d.team_a)
        team_b_count = sum(1 for v in votes if v.pick == d.team_b)

        f_tally = self.font("bold", 30)
        tally_text = f"VOTE: {team_a_count}-{team_b_count}"
        if team_a_count > team_b_count:
            tally_text += f" {d.team_a.upper()}"
        elif team_b_count > team_a_count:
            tally_text += f" {d.team_b.upper()}"
        else:
            tally_text += " TIED"

        draw.text((self.w // 2, y), tally_text, fill=WHITE, font=f_tally, anchor="mt")

        # Agent indicators row
        f_ind = self.font("regular", 22)
        total_agents = len(all_agent_names)
        spacing = self.s(150)
        start_x = (self.w - (total_agents - 1) * spacing) // 2
        ind_y = y + self.s(50)

        for i, name in enumerate(all_agent_names):
            x = start_x + i * spacing
            cfg = AGENT_VOICES.get(name, {})
            color = cfg.get("color", DIM_GRAY)

            if name.title() in voted or name in voted:
                v = voted.get(name.title()) or voted.get(name)
                if v.pick == d.team_a:
                    indicator_color = GREEN_CHECK
                    marker = "A"
                else:
                    indicator_color = RED_ALERT
                    marker = "B"
                # Small circle
                draw.ellipse(
                    (x - self.s(16), ind_y, x + self.s(16), ind_y + self.s(32)),
                    fill=_darken(color, 0.5), outline=color, width=self.s(2))
                draw.text((x, ind_y + self.s(16)),
                          marker, fill=indicator_color, font=f_ind, anchor="mm")
            else:
                # Not yet voted — dim circle
                draw.ellipse(
                    (x - self.s(16), ind_y, x + self.s(16), ind_y + self.s(32)),
                    fill=_darken(DIM_GRAY, 0.3), outline=CARD_BORDER, width=self.s(1))


# ---------------------------------------------------------------------------
# Audio generation (ElevenLabs)
# ---------------------------------------------------------------------------
class AudioGenerator:
    """Generates per-agent audio clips via ElevenLabs API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.Client(
            timeout=60.0,
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        )
        self.chars_used = 0

    def synthesize(self, text: str, voice_id: str,
                   stability: float = 0.5, similarity_boost: float = 0.75) -> bytes:
        """TTS via ElevenLabs, returns MP3 bytes."""
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
            },
        }
        last_error = None
        for attempt in range(3):
            try:
                resp = self.client.post(url, json=payload)
                if resp.status_code == 200:
                    self.chars_used += len(text)
                    return resp.content
                elif resp.status_code == 429:
                    wait = 2 ** attempt * 5
                    logger.warning("Rate limited, retrying in %ds... (attempt %d/3)", wait, attempt + 1)
                    print(f"    Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                    last_error = RuntimeError(f"Rate limited (HTTP 429)")
                else:
                    logger.error("ElevenLabs API error %d: %s", resp.status_code, resp.text[:200])
                    print(f"    ElevenLabs error {resp.status_code}: {resp.text[:200]}")
                    last_error = RuntimeError(f"ElevenLabs API error {resp.status_code}: {resp.text[:200]}")
                    resp.raise_for_status()
            except httpx.TimeoutException as e:
                wait = 2 ** attempt * 5
                logger.warning("Request timed out, retrying in %ds... (attempt %d/3)", wait, attempt + 1)
                print(f"    Request timed out, retrying in {wait}s...")
                time.sleep(wait)
                last_error = e
            except httpx.HTTPStatusError as e:
                last_error = e
                break
            except Exception as e:
                logger.error("Unexpected error during TTS synthesis: %s", e)
                last_error = e
                break
        raise RuntimeError(f"Failed after 3 retries: {last_error}")

    def generate_agent_audio(self, agent_name: str, text: str, output_path: Path) -> Optional[Path]:
        """Generate audio for a single agent's line. Returns None on failure."""
        voice_cfg = None
        for name, cfg in AGENT_VOICES.items():
            if name.lower() == agent_name.lower():
                voice_cfg = cfg
                break
        if not voice_cfg:
            voice_cfg = NARRATOR_VOICE

        print(f"    TTS: {agent_name} ({len(text)} chars)")
        try:
            audio_bytes = self.synthesize(
                text=text,
                voice_id=voice_cfg["voice_id"],
                stability=voice_cfg.get("stability", 0.5),
                similarity_boost=voice_cfg.get("similarity_boost", 0.75),
            )
        except Exception as e:
            logger.error("Failed to generate audio for agent '%s': %s", agent_name, e)
            print(f"    Warning: TTS failed for {agent_name}: {e} — skipping audio")
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        return output_path

    def generate_narrator_audio(self, text: str, output_path: Path) -> Optional[Path]:
        """Generate narrator audio. Returns None on failure."""
        print(f"    TTS: Narrator ({len(text)} chars)")
        try:
            audio_bytes = self.synthesize(
                text=text,
                voice_id=NARRATOR_VOICE["voice_id"],
                stability=NARRATOR_VOICE.get("stability", 0.7),
                similarity_boost=NARRATOR_VOICE.get("similarity_boost", 0.75),
            )
        except Exception as e:
            logger.error("Failed to generate narrator audio: %s", e)
            print(f"    Warning: TTS failed for narrator: {e} — skipping audio")
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        return output_path

    def close(self):
        self.client.close()


def generate_silence_wav(duration_seconds: float, output_path: Path, sample_rate: int = 44100):
    """Generate a silent WAV file."""
    num_samples = int(sample_rate * duration_seconds)
    # WAV header + silent data
    data = b'\x00\x00' * num_samples  # 16-bit silence, mono
    header = struct.pack('<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + len(data), b'WAVE',
        b'fmt ', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b'data', len(data))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(header + data)
    return output_path


# ---------------------------------------------------------------------------
# Video assembly
# ---------------------------------------------------------------------------
def build_video(debate: ParsedDebate, audio_dir: Optional[Path],
                output_path: Path, preview: bool = False,
                no_audio: bool = False, dry_run: bool = False):
    """Build the full MP4 video from debate data and audio files."""
    scale = PREVIEW_SCALE if preview else 1.0
    renderer = FrameRenderer(debate, scale=scale)
    fps = FPS

    clips = []
    audio_clips = []
    current_time = 0.0

    def make_still_clip(img: Image.Image, duration: float) -> ImageClip:
        """Convert a PIL Image to a moviepy ImageClip. Closes the PIL image after conversion."""
        arr = np.array(img)
        img.close()
        return ImageClip(arr).with_duration(duration)

    def try_load_audio(path: Path) -> Optional[AudioFileClip]:
        """Try to load an audio clip, return None if missing."""
        if path and path.exists() and not no_audio and not dry_run:
            try:
                return AudioFileClip(str(path))
            except Exception as e:
                print(f"    Warning: could not load audio {path}: {e}")
        return None

    # --- INTRO (3 seconds) ---
    print("  Rendering intro...")
    intro_img = renderer.render_intro()
    intro_clip = make_still_clip(intro_img, 3.0)
    clips.append(intro_clip)

    # Intro audio
    if audio_dir and not no_audio:
        intro_audio = try_load_audio(audio_dir / "narrator_intro.mp3")
        if intro_audio:
            audio_clips.append(intro_audio.with_start(current_time))
            # Extend intro if audio is longer
            if intro_audio.duration > 3.0:
                clips[-1] = make_still_clip(intro_img, intro_audio.duration + 0.5)
    current_time += clips[-1].duration

    # --- AGENT ARGUMENTS ---
    votes_so_far = []
    for idx, agent in enumerate(debate.agents):
        print(f"  Rendering agent {idx+1}/{len(debate.agents)}: {agent.agent_name}...")

        # Determine clip duration
        base_duration = 7.0
        agent_audio = None
        if audio_dir and not no_audio:
            safe_name = agent.agent_name.lower().replace(" ", "_")
            agent_audio = try_load_audio(audio_dir / f"{safe_name}.mp3")
            if agent_audio:
                base_duration = max(base_duration, agent_audio.duration + 1.0)

        # Create frames with text animation
        # Text progresses from 0 to 1 over the first 70% of the clip
        text_anim_duration = base_duration * 0.7
        num_text_frames = max(2, int(text_anim_duration * 4))  # 4 keyframes/sec for text

        # We'll use a single frame approach with text fully shown for simplicity in rendering
        # but add a quick fade-in and then show text progressively
        frame_segments = []

        # Brief fade-in (0.3s) — just show the card appearing
        fade_dur = 0.3
        partial_img = renderer.render_agent_card(agent, text_progress=0.0,
                                                  votes_so_far=votes_so_far)
        frame_segments.append(make_still_clip(partial_img, fade_dur))

        # Text reveal phases (show text in 4-5 steps)
        steps = 5
        step_dur = text_anim_duration / steps
        for s in range(1, steps + 1):
            progress = s / steps
            step_img = renderer.render_agent_card(agent, text_progress=progress,
                                                   votes_so_far=votes_so_far)
            frame_segments.append(make_still_clip(step_img, step_dur))

        # Hold on final frame with pick badge
        hold_dur = base_duration - fade_dur - text_anim_duration
        if hold_dur < 1.0:
            hold_dur = 1.5
        final_img = renderer.render_agent_card(agent, text_progress=1.0,
                                                votes_so_far=votes_so_far)
        frame_segments.append(make_still_clip(final_img, hold_dur))

        agent_clip = concatenate_videoclips(frame_segments)
        clips.append(agent_clip)

        # Audio for this agent
        if agent_audio:
            audio_clips.append(agent_audio.with_start(current_time + 0.3))

        current_time += agent_clip.duration
        votes_so_far.append(agent)

    # --- VOTE TALLY (3 seconds) ---
    print("  Rendering vote tally...")
    tally_img = renderer.render_vote_tally(debate.agents)
    tally_duration = 3.0
    clips.append(make_still_clip(tally_img, tally_duration))
    current_time += tally_duration

    # --- CONDUCTOR VERDICT ---
    if debate.conductor:
        print("  Rendering conductor verdict...")
        conductor_duration = 7.0
        conductor_audio = None
        if audio_dir and not no_audio:
            conductor_audio = try_load_audio(audio_dir / "the_conductor.mp3")
            if conductor_audio:
                conductor_duration = max(conductor_duration, conductor_audio.duration + 1.5)

        # Text reveal for conductor
        cond_segments = []
        # Brief pause
        pause_img = renderer._base_frame() if not hasattr(renderer, 'render_conductor') else \
            renderer.render_conductor(text_progress=0.0, votes=debate.agents)
        cond_segments.append(make_still_clip(
            renderer.render_conductor(text_progress=0.0, votes=debate.agents), 0.5))

        steps = 4
        step_dur = (conductor_duration * 0.6) / steps
        for s in range(1, steps + 1):
            p = s / steps
            cond_segments.append(make_still_clip(
                renderer.render_conductor(text_progress=p, votes=debate.agents), step_dur))

        hold = conductor_duration - 0.5 - conductor_duration * 0.6
        if hold < 1.5:
            hold = 1.5
        cond_segments.append(make_still_clip(
            renderer.render_conductor(text_progress=1.0, votes=debate.agents), hold))

        conductor_clip = concatenate_videoclips(cond_segments)
        clips.append(conductor_clip)

        if conductor_audio:
            audio_clips.append(conductor_audio.with_start(current_time + 0.5))
        current_time += conductor_clip.duration

    # --- OUTRO (3 seconds) ---
    print("  Rendering outro...")
    outro_img = renderer.render_outro()
    clips.append(make_still_clip(outro_img, 3.0))
    current_time += 3.0

    # --- COMPOSITE ---
    print(f"  Compositing video ({current_time:.1f}s total)...")
    final_video = concatenate_videoclips(clips)

    if audio_clips:
        composite_audio = CompositeAudioClip(audio_clips)
        final_video = final_video.with_audio(composite_audio)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    codec = "libx264"
    audio_codec = "aac" if audio_clips else None
    bitrate = "2000k" if preview else "5000k"

    lock_path = output_path.with_suffix(".lock")
    lock_fd = None
    try:
        print(f"  Writing {output_path}...")
        # Acquire file lock to prevent concurrent writes to same output
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        final_video.write_videofile(
            str(output_path),
            fps=fps,
            codec=codec,
            audio_codec=audio_codec,
            bitrate=bitrate,
            logger=None,  # Suppress moviepy progress bar
            threads=2,
        )

        file_size = output_path.stat().st_size / (1024 * 1024)
        print(f"  Done: {output_path} ({file_size:.1f} MB, {current_time:.1f}s)")
    except Exception as e:
        logger.error("Failed to write video %s: %s", output_path, e)
        print(f"  Error writing video: {e}")
        raise
    finally:
        # Always clean up clips and lock
        final_video.close()
        for c in clips:
            try:
                c.close()
            except Exception:
                pass
        for a in audio_clips:
            try:
                a.close()
            except Exception:
                pass
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except Exception:
                pass
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Orchestration: generate audio + video for a debate
# ---------------------------------------------------------------------------
def generate_debate_video(debate: ParsedDebate, debate_file: Path,
                          audio_gen: Optional[AudioGenerator] = None,
                          preview: bool = False, no_audio: bool = False,
                          dry_run: bool = False, audio_only: bool = False,
                          select_agents: list[str] = None):
    """Full pipeline: parse debate, generate audio, build video."""
    stem = debate_file.stem
    video_path = VIDEOS_DIR / f"{stem}.mp4"
    audio_dir = VIDEOS_DIR / f"{stem}_audio"

    # --- Audio generation ---
    if not dry_run and not no_audio and audio_gen:
        print(f"\n  Generating audio for {stem}...")
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Narrator intro
        d = debate
        intro_text = (
            f"Welcome to the March Madness Agent Swarm. "
            f"Number {d.seed_a} {d.team_a} versus number {d.seed_b} {d.team_b}. "
            f"{d.round_label}, {d.region}. Let's hear from the panel."
        )
        audio_gen.generate_narrator_audio(intro_text, audio_dir / "narrator_intro.mp3")

        # Agent audio
        for agent in debate.agents:
            if select_agents and agent.agent_name.lower() not in [s.lower() for s in select_agents]:
                continue
            safe_name = agent.agent_name.lower().replace(" ", "_")
            text = agent.quote
            if agent.pick and agent.confidence:
                text += f" My pick: {agent.pick}, {agent.confidence} percent confidence."
            audio_gen.generate_agent_audio(agent.agent_name, text, audio_dir / f"{safe_name}.mp3")

        # Conductor audio
        if debate.conductor:
            c = debate.conductor
            text = c.quote
            if c.pick and c.confidence:
                text += f" The final pick is {c.pick} at {c.confidence} percent."
            audio_gen.generate_agent_audio("The Conductor", text, audio_dir / "the_conductor.mp3")

        print(f"  Audio generated ({audio_gen.chars_used} chars used this session)")

        if audio_only:
            print(f"  Audio-only mode — skipping video render.")
            return

    # Use audio_dir if it exists and has files
    effective_audio_dir = None
    if audio_dir.exists() and any(audio_dir.glob("*.mp3")) and not no_audio and not dry_run:
        effective_audio_dir = audio_dir

    # --- Video generation ---
    if not audio_only:
        print(f"\n  Building video: {video_path}")
        build_video(debate, effective_audio_dir, video_path,
                    preview=preview, no_audio=no_audio, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Character usage estimation
# ---------------------------------------------------------------------------
def estimate_chars(debate: ParsedDebate) -> int:
    """Estimate total ElevenLabs characters for a debate."""
    total = 0
    d = debate
    intro = (f"Welcome to the March Madness Agent Swarm. "
             f"Number {d.seed_a} {d.team_a} versus number {d.seed_b} {d.team_b}. "
             f"{d.round_label}, {d.region}. Let's hear from the panel.")
    total += len(intro)
    for agent in debate.agents:
        text = agent.quote
        if agent.pick:
            text += f" My pick: {agent.pick}, {agent.confidence} percent confidence."
        total += len(text)
    if debate.conductor:
        c = debate.conductor
        text = c.quote
        if c.pick:
            text += f" The final pick is {c.pick} at {c.confidence} percent."
        total += len(text)
    return total


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Generate short-form debate videos from March Madness Agent Swarm transcripts."
    )
    parser.add_argument("--debate", type=Path, help="Path to a debate .md file")
    parser.add_argument("--game-id", type=str, help="Game ID to look up in debates/")
    parser.add_argument("--round", type=str, help="Generate videos for all games in a round (e.g. R64)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate video with silent audio placeholders (no API calls)")
    parser.add_argument("--preview", action="store_true",
                        help="Half-resolution preview (faster render)")
    parser.add_argument("--no-audio", action="store_true",
                        help="Generate video with no audio track")
    parser.add_argument("--audio-only", action="store_true",
                        help="Only generate audio files, skip video render")
    parser.add_argument("--select-agents", type=str, nargs="+",
                        help="Only generate audio for these agents")
    parser.add_argument("--caption", action="store_true",
                        help="Burn in SRT-style captions (text is always shown)")
    args = parser.parse_args()

    if not args.debate and not args.game_id and not args.round:
        parser.print_help()
        sys.exit(1)

    # Collect debate files
    debate_files = []
    if args.debate:
        if not args.debate.exists():
            print(f"File not found: {args.debate}")
            sys.exit(1)
        debate_files = [args.debate]
    elif args.game_id:
        # Search debates/ for matching file
        for f in DEBATES_DIR.glob("*.md"):
            if args.game_id.lower() in f.stem.lower():
                debate_files.append(f)
        if not debate_files:
            print(f"No debate file found matching game_id: {args.game_id}")
            sys.exit(1)
    elif args.round:
        pattern = f"{args.round}_*.md"
        debate_files = sorted(DEBATES_DIR.glob(pattern))
        if not debate_files:
            print(f"No debate files found for round: {args.round}")
            sys.exit(1)

    print(f"{'='*60}")
    print(f"March Madness Agent Swarm — Video Generator")
    print(f"{'='*60}")
    print(f"Files: {len(debate_files)}")
    print(f"Mode: {'dry-run' if args.dry_run else 'preview' if args.preview else 'full'}")
    if args.no_audio:
        print(f"Audio: disabled")
    if args.audio_only:
        print(f"Video: disabled (audio-only)")

    # Parse all debates
    debates = []
    for f in debate_files:
        try:
            debate = parse_debate_markdown(f)
            # Validate parse results
            errors = validate_parsed_debate(debate)
            if errors:
                print(f"Warning: parse issues in {f}:")
                for err in errors:
                    print(f"  - {err}")
                print(f"  Skipping {f}")
                continue
            debates.append((f, debate))
        except Exception as e:
            print(f"Error parsing {f}: {e}")
            import traceback
            traceback.print_exc()

    if not debates:
        print("No debates parsed successfully.")
        sys.exit(1)

    # Estimate characters
    total_chars = sum(estimate_chars(d) for _, d in debates)
    print(f"Estimated ElevenLabs characters: {total_chars:,}")
    print(f"Estimated cost: ~${total_chars * 0.00003:.4f}")
    print()

    # Set up audio generator
    audio_gen = None
    if not args.dry_run and not args.no_audio:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if api_key and api_key != "el-xxxxx":
            audio_gen = AudioGenerator(api_key)
            print("ElevenLabs API: connected")
        else:
            print("ElevenLabs API: not configured (will generate silent video)")
            print("  Set ELEVENLABS_API_KEY in .env to enable voice generation")
            if not args.audio_only:
                args.no_audio = True

    # Generate videos
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    for debate_file, debate in debates:
        print(f"\n{'='*60}")
        print(f"  {debate.team_a} vs {debate.team_b} ({debate.round_label}, {debate.region})")
        print(f"{'='*60}")

        generate_debate_video(
            debate, debate_file,
            audio_gen=audio_gen,
            preview=args.preview,
            no_audio=args.no_audio or args.dry_run,
            dry_run=args.dry_run,
            audio_only=args.audio_only,
            select_agents=args.select_agents,
        )

    if audio_gen:
        print(f"\nTotal ElevenLabs characters used: {audio_gen.chars_used:,}")
        audio_gen.close()

    print(f"\nAll done! Output in {VIDEOS_DIR}/")


if __name__ == "__main__":
    main()
