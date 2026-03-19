#!/usr/bin/env python3
"""Generate all 18 HeyGen avatar clips for Louisville vs USF debate video."""

import json
import os
import time
import urllib.request

API_KEY = os.environ["HEYGEN_API_KEY"]
CLIPS_DIR = os.path.join(os.path.dirname(__file__), "clips")

# Avatar + Voice assignments
AGENTS = {
    "Tempo Hawk":   {"avatar": "Jonas_expressive_2024112701",  "voice": "6ad549fcd687425886a4387e9197a1cb"},
    "Iron Curtain": {"avatar": "Marcus_expressive_2024120201", "voice": "9caef63304614c39b5397f2ce9431baf"},
    "Glass Cannon": {"avatar": "Brandon_expressive_public",    "voice": "645bbfb44ed94fcdab417539da543f12"},
    "Road Dog":     {"avatar": "chad_expressive_20240910",     "voice": "9a2d2c7598814e7fbe3717026b0bef0d"},
    "Whisper":      {"avatar": "Jin_expressive_2024112501",    "voice": "cef3bc4e0a84424cafcde6f2cf466c97"},
    "Oracle":       {"avatar": "Silas_expressive_2024120201",  "voice": "828b59f834fd4c7950873117368baf6"},
    "Streak":       {"avatar": "Vince_expressive_2024112701",  "voice": "2992d98466df4dc7950873117368baf6"},
    "Conductor":    {"avatar": "Teodor_expressive_2024112701", "voice": "69ab9617a561446992605c2c7924aacb"},
}

# Scene definitions: (filename, agent_name, script_text)
SCENES = [
    # Scene 1: Conductor intro
    ("scene01_conductor_intro", "Conductor",
     "Welcome to the March Madness Agent Swarm. Seven AI specialists are about to debate one of the most compelling matchups in the East Region. Number 6 Louisville versus number 11 USF. Let's get into it."),

    # Round 1 — Independent Analysis
    ("scene02_r1_tempo_hawk", "Tempo Hawk",
     "Identical tempos neutralize pace advantage. Both teams play at 67.5 possessions per game. USF's health and championship momentum beats Louisville's injury uncertainty in a grinding half-court game."),

    ("scene03_r1_iron_curtain", "Iron Curtain",
     "Louisville is missing their 18.2 points per game floor general against USF's suffocating defense. USF allows just 41.3% shooting. This defensive battle favors the healthier, more experienced backcourt."),

    ("scene04_r1_glass_cannon", "Glass Cannon",
     "Louisville's three point percentage is barely better, but USF has the hot hand! They just won their conference! One hot night from Wes Enis or Pinion and it's OVER! I'm leaning Louisville but barely."),

    ("scene05_r1_road_dog", "Road Dog",
     "USF's senior-led roster just won their conference. Louisville's coach hasn't been here before. I've seen this movie. Experience wins in March, and USF has the edge at 7 out of 10 versus Louisville's 6."),

    ("scene06_r1_whisper", "Whisper",
     "Everyone knows about Brown's back injury. But his absence isn't just points. It's a huge chemistry disruption. Louisville is missing 18.2 points per game, and that changes everything about their offensive identity."),

    ("scene07_r1_oracle", "Oracle",
     "Classic 6 versus 11 upset setup. USF are conference champions, peaking at the right time. Louisville is missing their 18.2 point scorer Brown Junior. This reminds me of 2018 Miami-Loyola upset dynamics. Eleven seeds win 37.5% historically."),

    ("scene08_r1_streak", "Streak",
     "Forget the spreadsheets! USF just won their conference tournament, riding a four game win streak, playing their best basketball right now. Louisville is fading, losing their last game. Momentum is real!"),

    # Scenes 9 is a title card (no avatar needed)

    # Round 2 — Cross-Examination
    ("scene10_r2_tempo_hawk", "Tempo Hawk",
     "Oracle's wrong. Eleven seeds don't win because they're peaking. They win by controlling tempo. USF's grinding pace neutralizes Louisville's talent edge. I'm even more confident now. Louisville drops to 38%."),

    ("scene11_r2_iron_curtain", "Iron Curtain",
     "Glass Cannon ignores the reality. Hot shooting dies in March. Defense travels. USF's defense will grind Louisville into dust without Brown. Whisper nailed it. This isn't just about points, it's chemistry destruction."),

    ("scene12_r2_glass_cannon", "Glass Cannon",
     "Iron Curtain keeps talking defense, but one hot shooter changes everything! USF's three point percentage is 35.5 versus Louisville's 35.8. That's too close! One hot quarter and it's over! I'm weakening though."),

    ("scene13_r2_road_dog", "Road Dog",
     "Oracle loves the numbers, but a coach's first tournament with a blue blood is different. USF's senior leadership and recent conference title is a proven upset recipe. I'm even more confident in USF."),

    ("scene14_r2_whisper", "Whisper",
     "Everyone's missing the deeper layer. Brown's injury doesn't just cut points. It forces a scheme change. A complete disruption. Chemistry suffers when rotations shift this late in the season."),

    ("scene15_r2_oracle", "Oracle",
     "Glass Cannon ignores history. Hot streaks don't predict March success. 2019 Auburn shot 42% from three in the SEC tournament and then lost in the first round. I'm weakening on Louisville but still lean their way."),

    ("scene16_r2_streak", "Streak",
     "Oracle wants to talk about history. I care about right now! USF just won four straight to win their conference. Louisville is slumping, losing their last game. Momentum is real and I'm strengthened!"),

    # Scene 17: Conductor verdict (we already have this but regenerate for consistency)
    ("scene17_conductor_verdict", "Conductor",
     "Iron Curtain and Tempo Hawk won this debate. Defense travels, pace neutralizes talent gaps. Missing Brown's 18.2 points per game against elite defense is decisive. Our pick: USF. Sometimes the upset is just math."),
]


def api_request(url, data=None, method="GET"):
    """Make authenticated HeyGen API request."""
    if data:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
            method="POST",
        )
    else:
        req = urllib.request.Request(url, headers={"X-Api-Key": API_KEY})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def generate_video(agent_name, script_text):
    """Submit a video generation job, return video_id."""
    agent = AGENTS[agent_name]
    payload = {
        "video_inputs": [{
            "character": {
                "type": "avatar",
                "avatar_id": agent["avatar"],
                "avatar_style": "normal",
            },
            "voice": {
                "type": "text",
                "input_text": script_text,
                "voice_id": agent["voice"],
            },
        }],
        "dimension": {"width": 1920, "height": 1080},
    }
    result = api_request("https://api.heygen.com/v2/video/generate", data=payload)
    return result["data"]["video_id"]


def check_status(video_id):
    """Return (status, video_url, duration)."""
    result = api_request(
        f"https://api.heygen.com/v1/video_status.get?video_id={video_id}"
    )
    d = result["data"]
    return d["status"], d.get("video_url"), d.get("duration")


def download(url, path):
    urllib.request.urlretrieve(url, path)


def main():
    os.makedirs(CLIPS_DIR, exist_ok=True)

    # Check which clips already exist
    existing = set()
    for f in os.listdir(CLIPS_DIR):
        if f.endswith(".mp4"):
            existing.add(f.replace(".mp4", ""))

    # Submit all jobs
    jobs = {}  # video_id -> (filename, agent_name)
    for filename, agent_name, script in SCENES:
        if filename in existing:
            print(f"SKIP {filename} (already exists)")
            continue
        print(f"SUBMIT {filename} ({agent_name})...")
        try:
            vid = generate_video(agent_name, script)
            jobs[vid] = filename
            print(f"  -> video_id: {vid}")
            time.sleep(1)  # rate limit courtesy
        except Exception as e:
            print(f"  ERROR: {e}")

    if not jobs:
        print("All clips already generated!")
        return

    # Poll for completion
    print(f"\nWaiting for {len(jobs)} clips to render...")
    pending = dict(jobs)
    while pending:
        time.sleep(15)
        still_pending = {}
        for vid, filename in pending.items():
            status, url, duration = check_status(vid)
            if status == "completed":
                outpath = os.path.join(CLIPS_DIR, f"{filename}.mp4")
                print(f"DONE {filename} ({duration:.1f}s) -> downloading...")
                download(url, outpath)
            elif status == "failed":
                print(f"FAILED {filename}!")
            else:
                still_pending[vid] = filename
        pending = still_pending
        if pending:
            print(f"  ...{len(pending)} still rendering...")

    print("\nAll clips generated!")


if __name__ == "__main__":
    main()
