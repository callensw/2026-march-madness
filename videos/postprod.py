#!/usr/bin/env python3
"""Post-production pipeline for Louisville vs USF debate video.

Generates title cards, overlays lower-thirds/probability bars on clips,
and stitches everything into a final video with crossfade transitions.
"""

import os
import subprocess
import json
import shutil
from PIL import Image, ImageDraw, ImageFont

# Use imageio-ffmpeg bundled binary if system ffmpeg unavailable
def get_ffmpeg():
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"

def get_ffprobe():
    if shutil.which("ffprobe"):
        return "ffprobe"
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        ffprobe_path = ffmpeg_path.replace("ffmpeg-", "ffprobe-")
        if os.path.exists(ffprobe_path):
            return ffprobe_path
        # Try sibling directory
        bindir = os.path.dirname(ffmpeg_path)
        for f in os.listdir(bindir):
            if "ffprobe" in f:
                return os.path.join(bindir, f)
    except ImportError:
        pass
    return "ffprobe"

FFMPEG = get_ffmpeg()
FFPROBE = get_ffprobe()

VIDEOS_DIR = os.path.dirname(os.path.abspath(__file__))
CLIPS_DIR = os.path.join(VIDEOS_DIR, "clips")
ASSETS_DIR = os.path.join(VIDEOS_DIR, "assets")
OVERLAY_DIR = os.path.join(VIDEOS_DIR, "overlaid")
FINAL_OUTPUT = os.path.join(VIDEOS_DIR, "louisville_vs_usf_final.mp4")

W, H = 1920, 1080

# Agent metadata
AGENT_META = {
    "Tempo Hawk":   {"emoji": "\U0001f985", "color": "#4FC3F7", "model": "Claude", "vote": "USF"},
    "Iron Curtain": {"emoji": "\U0001f6e1\ufe0f",  "color": "#EF5350", "model": "Claude", "vote": "USF"},
    "Glass Cannon": {"emoji": "\U0001f4a5", "color": "#FFB74D", "model": "Gemini", "vote": "Louisville"},
    "Road Dog":     {"emoji": "\U0001f43a", "color": "#81C784", "model": "Gemini", "vote": "USF"},
    "Whisper":      {"emoji": "\U0001f441\ufe0f",  "color": "#CE93D8", "model": "Gemini", "vote": "USF"},
    "Oracle":       {"emoji": "\U0001f4dc", "color": "#FFF176", "model": "Claude", "vote": "Louisville"},
    "Streak":       {"emoji": "\U0001f525", "color": "#FF8A65", "model": "Gemini", "vote": "USF"},
    "Conductor":    {"emoji": "\U0001f3bc", "color": "#FFFFFF", "model": "Claude", "vote": "USF"},
}

# Win probabilities from debate (Louisville probability)
R1_PROBS = {
    "Tempo Hawk": 0.42, "Iron Curtain": 0.42, "Glass Cannon": 0.55,
    "Road Dog": 0.48, "Whisper": 0.48, "Oracle": 0.58, "Streak": 0.45,
}
R2_PROBS = {
    "Tempo Hawk": 0.38, "Iron Curtain": 0.38, "Glass Cannon": 0.52,
    "Road Dog": 0.45, "Whisper": 0.45, "Oracle": 0.52, "Streak": 0.42,
}

# Position changes in Round 2
R2_POSITIONS = {
    "Tempo Hawk": "STRENGTHENED", "Iron Curtain": "STRENGTHENED",
    "Glass Cannon": "WEAKENED", "Road Dog": "STRENGTHENED",
    "Whisper": "STRENGTHENED", "Oracle": "WEAKENED", "Streak": "STRENGTHENED",
}

POSITION_COLORS = {
    "STRENGTHENED": "#4CAF50",
    "WEAKENED": "#FFC107",
    "FLIPPED": "#F44336",
}


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def get_font(size, bold=False):
    """Get a font, falling back gracefully."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_gradient_bg(draw, w, h):
    """Dark navy gradient background with subtle grid."""
    top = (10, 15, 26)      # #0a0f1a
    bottom = (15, 22, 38)   # #0f1626
    for y in range(h):
        r = int(top[0] + (bottom[0] - top[0]) * y / h)
        g = int(top[1] + (bottom[1] - top[1]) * y / h)
        b = int(top[2] + (bottom[2] - top[2]) * y / h)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    # Subtle grid
    grid_color = (25, 35, 55, 80)
    for x in range(0, w, 60):
        draw.line([(x, 0), (x, h)], fill=grid_color, width=1)
    for y in range(0, h, 60):
        draw.line([(0, y), (w, y)], fill=grid_color, width=1)


def create_title_card(text_lines, filename, accent_color="#4FC3F7", badge=None):
    """Create a title card image."""
    img = Image.new("RGBA", (W, H), (10, 15, 26, 255))
    draw = ImageDraw.Draw(img)
    draw_gradient_bg(draw, W, H)

    # Accent line
    accent_rgb = hex_to_rgb(accent_color)
    draw.rectangle([(0, H//2 - 120), (W, H//2 - 115)], fill=accent_rgb + (180,))
    draw.rectangle([(0, H//2 + 115), (W, H//2 + 120)], fill=accent_rgb + (180,))

    # Text
    y_start = H // 2 - 80
    for i, (text, size) in enumerate(text_lines):
        font = get_font(size, bold=(i == 0))
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2
        color = (255, 255, 255) if i == 0 else (180, 190, 210)
        draw.text((x, y_start), text, font=font, fill=color)
        y_start += size + 15

    # Badge
    if badge:
        font_badge = get_font(28, bold=True)
        bw = draw.textbbox((0, 0), badge, font=font_badge)
        bw = bw[2] - bw[0] + 40
        bx = (W - bw) // 2
        by = y_start + 20
        draw.rounded_rectangle([(bx, by), (bx + bw, by + 45)], radius=8,
                               fill=(244, 67, 54, 220))
        draw.text((bx + 20, by + 8), badge, font=font_badge, fill=(255, 255, 255))

    path = os.path.join(ASSETS_DIR, filename)
    img.save(path)
    return path


def create_lower_third_overlay(agent_name, round_num):
    """Create a transparent PNG overlay with lower-third + probability bar."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    meta = AGENT_META[agent_name]
    accent = hex_to_rgb(meta["color"])

    # Lower third background
    lt_y = H - 100
    draw.rectangle([(0, lt_y), (W, H)], fill=(10, 15, 26, 200))
    # Accent left border
    draw.rectangle([(0, lt_y), (8, H)], fill=accent + (255,))
    # Top line
    draw.rectangle([(0, lt_y), (W, lt_y + 2)], fill=accent + (150,))

    # Agent name + model
    font_name = get_font(32, bold=True)
    font_model = get_font(22)
    name_text = f"{meta['emoji']}  {agent_name.upper()}"
    model_text = f"Model: {meta['model']}"
    draw.text((25, lt_y + 18), name_text, font=font_name, fill=(255, 255, 255))
    name_w = draw.textbbox((0, 0), name_text, font=font_name)[2] + 40
    draw.text((name_w, lt_y + 24), f"|  {model_text}", font=font_model, fill=(160, 170, 190))

    # Vote indicator on the right
    vote = meta["vote"]
    font_vote = get_font(26, bold=True)
    vote_text = f"PICK: {vote.upper()}"
    vote_w = draw.textbbox((0, 0), vote_text, font=font_vote)[2]
    vote_color = (129, 199, 132) if vote == "USF" else (239, 83, 80)
    draw.text((W - vote_w - 30, lt_y + 22), vote_text, font=font_vote, fill=vote_color)

    # Probability bar (upper right)
    probs = R1_PROBS if round_num == 1 else R2_PROBS
    if agent_name in probs:
        lou_prob = probs[agent_name]
        usf_prob = 1 - lou_prob

        bar_x, bar_y = W - 380, 30
        bar_w, bar_h = 350, 35
        font_prob = get_font(18, bold=True)
        font_label = get_font(16)

        # Background
        draw.rounded_rectangle([(bar_x - 10, bar_y - 30), (bar_x + bar_w + 10, bar_y + bar_h + 25)],
                               radius=8, fill=(10, 15, 26, 200))

        # Labels
        draw.text((bar_x, bar_y - 25), "Louisville", font=font_label, fill=(200, 200, 200))
        usf_label = "USF"
        usf_lw = draw.textbbox((0, 0), usf_label, font=font_label)[2]
        draw.text((bar_x + bar_w - usf_lw, bar_y - 25), usf_label, font=font_label, fill=(200, 200, 200))

        # Bar
        draw.rounded_rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)],
                               radius=4, fill=(60, 60, 60))
        lou_w = int(bar_w * lou_prob)
        if lou_w > 0:
            draw.rounded_rectangle([(bar_x, bar_y), (bar_x + lou_w, bar_y + bar_h)],
                                   radius=4, fill=(239, 83, 80))
        # USF portion
        if lou_w < bar_w:
            draw.rounded_rectangle([(bar_x + lou_w, bar_y), (bar_x + bar_w, bar_y + bar_h)],
                                   radius=4, fill=(129, 199, 132))

        # Percentages
        lou_text = f"{lou_prob*100:.0f}%"
        usf_text = f"{usf_prob*100:.0f}%"
        draw.text((bar_x + 8, bar_y + 6), lou_text, font=font_prob, fill=(255, 255, 255))
        usf_tw = draw.textbbox((0, 0), usf_text, font=font_prob)[2]
        draw.text((bar_x + bar_w - usf_tw - 8, bar_y + 6), usf_text, font=font_prob, fill=(255, 255, 255))

    # Position badge for Round 2
    if round_num == 2 and agent_name in R2_POSITIONS:
        pos = R2_POSITIONS[agent_name]
        pos_color = hex_to_rgb(POSITION_COLORS[pos])
        font_pos = get_font(20, bold=True)
        pos_w = draw.textbbox((0, 0), pos, font=font_pos)[2] + 30
        px = 25
        py = 30
        draw.rounded_rectangle([(px, py), (px + pos_w, py + 35)],
                               radius=6, fill=pos_color + (220,))
        draw.text((px + 15, py + 6), pos, font=font_pos, fill=(255, 255, 255))

    path = os.path.join(ASSETS_DIR, f"overlay_{agent_name.lower().replace(' ', '_')}_r{round_num}.png")
    img.save(path)
    return path


def apply_overlay(clip_path, overlay_path, output_path):
    """Use ffmpeg to composite overlay PNG on top of clip with dark background."""
    # First, replace background with dark navy, then add overlay
    cmd = [
        FFMPEG, "-y",
        "-i", clip_path,
        "-i", overlay_path,
        "-filter_complex",
        # Darken the original background by blending with dark color
        "[0:v]colorbalance=rs=-0.3:gs=-0.3:bs=-0.2,eq=brightness=-0.15:saturation=0.8[darkened];"
        "[darkened][1:v]overlay=0:0[out]",
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "25",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def image_to_video(image_path, output_path, duration=5):
    """Convert a still image to a video clip."""
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", image_path,
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-c:v", "libx264", "-t", str(duration),
        "-pix_fmt", "yuv420p", "-r", "25",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def concat_with_crossfade(clip_paths, output_path, fade_dur=0.5):
    """Concatenate clips with crossfade transitions using ffmpeg xfade."""
    if len(clip_paths) == 0:
        return
    if len(clip_paths) == 1:
        subprocess.run(["cp", clip_paths[0], output_path], check=True)
        return

    # Get durations
    durations = []
    for p in clip_paths:
        cmd = [FFPROBE, "-v", "error", "-show_entries", "format=duration",
               "-of", "json", p]
        result = subprocess.run(cmd, capture_output=True, text=True)
        d = json.loads(result.stdout)["format"]["duration"]
        durations.append(float(d))

    # Build xfade filter chain
    n = len(clip_paths)
    inputs = []
    for p in clip_paths:
        inputs.extend(["-i", p])

    # Build complex filter
    filter_parts = []
    # First, ensure all inputs have audio
    for i in range(n):
        filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1:color=black[v{i}];")
        filter_parts.append(f"[{i}:a]aresample=44100[a{i}];")

    # Chain xfade for video
    offset = durations[0] - fade_dur
    if n == 2:
        filter_parts.append(f"[v0][v1]xfade=transition=fade:duration={fade_dur}:offset={offset}[vout];")
        filter_parts.append(f"[a0][a1]acrossfade=d={fade_dur}[aout]")
    else:
        # Chain: v0+v1->tmp0, tmp0+v2->tmp1, etc.
        filter_parts.append(f"[v0][v1]xfade=transition=fade:duration={fade_dur}:offset={offset}[vtmp0];")
        filter_parts.append(f"[a0][a1]acrossfade=d={fade_dur}[atmp0];")
        for i in range(2, n):
            offset += durations[i-1] - fade_dur
            prev_v = f"vtmp{i-2}"
            prev_a = f"atmp{i-2}"
            if i == n - 1:
                filter_parts.append(f"[{prev_v}][v{i}]xfade=transition=fade:duration={fade_dur}:offset={offset}[vout];")
                filter_parts.append(f"[{prev_a}][a{i}]acrossfade=d={fade_dur}[aout]")
            else:
                filter_parts.append(f"[{prev_v}][v{i}]xfade=transition=fade:duration={fade_dur}:offset={offset}[vtmp{i-1}];")
                filter_parts.append(f"[{prev_a}][a{i}]acrossfade=d={fade_dur}[atmp{i-1}];")

    filter_str = "\n".join(filter_parts)

    cmd = [FFMPEG, "-y"] + inputs + [
        "-filter_complex", filter_str,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "25",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def main():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(OVERLAY_DIR, exist_ok=True)

    print("=== STEP 1: Generate title cards ===")

    # Intro card
    intro_path = create_title_card([
        ("(6) LOUISVILLE  vs  (11) USF", 52),
        ("East Region — Round of 64", 32),
        ("March Madness Agent Swarm 2026", 28),
        ("\U0001f3c0  Seven AI Agents. One Pick.", 24),
    ], "intro_card.png", accent_color="#4FC3F7")
    print(f"  Created intro card")

    # Round 1 header
    r1_path = create_title_card([
        ("ROUND 1 — INDEPENDENT ANALYSIS", 48),
        ("(6) Louisville vs (11) USF — East Region", 30),
    ], "r1_header.png", accent_color="#4FC3F7")
    print(f"  Created R1 header")

    # Round 2 header
    r2_path = create_title_card([
        ("ROUND 2 — CROSS EXAMINATION", 48),
        ("Agents Challenge Each Other", 30),
    ], "r2_header.png", accent_color="#EF5350")
    print(f"  Created R2 header")

    # Outro card
    outro_img = Image.new("RGBA", (W, H), (10, 15, 26, 255))
    draw = ImageDraw.Draw(outro_img)
    draw_gradient_bg(draw, W, H)

    font_big = get_font(52, bold=True)
    font_med = get_font(32, bold=True)
    font_sm = get_font(24)
    font_vote = get_font(22)

    # UPSET PICK badge
    badge_text = "UPSET PICK: USF"
    bw = draw.textbbox((0, 0), badge_text, font=font_big)[2] + 50
    bx = (W - bw) // 2
    draw.rounded_rectangle([(bx, 100), (bx + bw, 170)], radius=12, fill=(244, 67, 54, 240))
    draw.text((bx + 25, 108), badge_text, font=font_big, fill=(255, 255, 255))

    # Vote tally
    draw.text((W//2 - 100, 220), "VOTE TALLY: 5-2 USF", font=font_med, fill=(129, 199, 132))

    # Agent breakdown
    agents_order = ["Tempo Hawk", "Iron Curtain", "Glass Cannon", "Road Dog", "Whisper", "Oracle", "Streak"]
    y = 290
    for agent in agents_order:
        m = AGENT_META[agent]
        vote_color = (129, 199, 132) if m["vote"] == "USF" else (239, 83, 80)
        accent = hex_to_rgb(m["color"])
        line = f"{m['emoji']}  {agent}"
        draw.text((500, y), line, font=font_vote, fill=accent + (255,))
        draw.text((850, y), m["vote"], font=font_vote, fill=vote_color)
        y += 38

    # Closing quote
    quote = '"Sometimes the upset is just math."'
    qw = draw.textbbox((0, 0), quote, font=font_sm)[2]
    draw.text(((W - qw)//2, H - 160), quote, font=font_sm, fill=(180, 190, 210))

    # Branding
    brand = "March Madness Agent Swarm 2026"
    brw = draw.textbbox((0, 0), brand, font=font_sm)[2]
    draw.text(((W - brw)//2, H - 100), brand, font=font_sm, fill=(100, 110, 130))

    outro_path = os.path.join(ASSETS_DIR, "outro_card.png")
    outro_img.save(outro_path)
    print(f"  Created outro card")

    # Convert title cards to video clips
    print("\n=== STEP 2: Convert cards to video ===")
    card_clips = {}
    for name, img_path, dur in [
        ("intro", intro_path, 5),
        ("r1_header", r1_path, 3),
        ("r2_header", r2_path, 3),
        ("outro", outro_path, 5),
    ]:
        out = os.path.join(OVERLAY_DIR, f"{name}.mp4")
        image_to_video(img_path, out, dur)
        card_clips[name] = out
        print(f"  {name}.mp4 ({dur}s)")

    print("\n=== STEP 3: Create overlays and apply to clips ===")
    agent_order = ["Tempo Hawk", "Iron Curtain", "Glass Cannon", "Road Dog", "Whisper", "Oracle", "Streak"]

    # Scene mapping: scene filename -> (agent_name, round)
    r1_scenes = [
        ("scene02_r1_tempo_hawk", "Tempo Hawk", 1),
        ("scene03_r1_iron_curtain", "Iron Curtain", 1),
        ("scene04_r1_glass_cannon", "Glass Cannon", 1),
        ("scene05_r1_road_dog", "Road Dog", 1),
        ("scene06_r1_whisper", "Whisper", 1),
        ("scene07_r1_oracle", "Oracle", 1),
        ("scene08_r1_streak", "Streak", 1),
    ]
    r2_scenes = [
        ("scene10_r2_tempo_hawk", "Tempo Hawk", 2),
        ("scene11_r2_iron_curtain", "Iron Curtain", 2),
        ("scene12_r2_glass_cannon", "Glass Cannon", 2),
        ("scene13_r2_road_dog", "Road Dog", 2),
        ("scene14_r2_whisper", "Whisper", 2),
        ("scene15_r2_oracle", "Oracle", 2),
        ("scene16_r2_streak", "Streak", 2),
    ]

    all_scenes = (
        [("scene01_conductor_intro", "Conductor", 1)]
        + r1_scenes + r2_scenes
        + [("scene17_conductor_verdict", "Conductor", 2)]
    )

    overlaid_clips = {}
    for scene_name, agent_name, rnd in all_scenes:
        clip_path = os.path.join(CLIPS_DIR, f"{scene_name}.mp4")
        if not os.path.exists(clip_path):
            print(f"  MISSING {clip_path}, skipping")
            continue

        overlay_path = create_lower_third_overlay(agent_name, rnd)
        out_path = os.path.join(OVERLAY_DIR, f"{scene_name}.mp4")
        print(f"  Overlaying {scene_name}...")
        apply_overlay(clip_path, overlay_path, out_path)
        overlaid_clips[scene_name] = out_path

    print("\n=== STEP 4: Stitch final video ===")
    # Build clip order
    final_order = [
        card_clips["intro"],                               # Intro card
        overlaid_clips.get("scene01_conductor_intro"),     # Conductor intro
        card_clips["r1_header"],                           # R1 header
    ]
    for scene_name, _, _ in r1_scenes:
        if scene_name in overlaid_clips:
            final_order.append(overlaid_clips[scene_name])
    final_order.append(card_clips["r2_header"])            # R2 header
    for scene_name, _, _ in r2_scenes:
        if scene_name in overlaid_clips:
            final_order.append(overlaid_clips[scene_name])
    if "scene17_conductor_verdict" in overlaid_clips:
        final_order.append(overlaid_clips["scene17_conductor_verdict"])
    final_order.append(card_clips["outro"])                 # Outro card

    # Remove None entries
    final_order = [p for p in final_order if p]

    print(f"  Stitching {len(final_order)} clips...")

    # Use simple concat (crossfade with many clips is fragile)
    # Write concat list
    concat_list = os.path.join(VIDEOS_DIR, "concat_list.txt")
    with open(concat_list, "w") as f:
        for p in final_order:
            f.write(f"file '{p}'\n")

    # Simple concat with re-encoding for consistency
    cmd = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "25",
        "-pix_fmt", "yuv420p",
        FINAL_OUTPUT,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FFMPEG ERROR: {result.stderr[-500:]}")
    else:
        size_mb = os.path.getsize(FINAL_OUTPUT) / 1024 / 1024
        print(f"\n  DONE! {FINAL_OUTPUT} ({size_mb:.1f} MB)")

    # Also copy to outputs
    output_copy = "/mnt/user-data/outputs/louisville_vs_usf_final.mp4"
    os.makedirs("/mnt/user-data/outputs", exist_ok=True)
    subprocess.run(["cp", FINAL_OUTPUT, output_copy])
    print(f"  Copied to {output_copy}")


if __name__ == "__main__":
    main()
