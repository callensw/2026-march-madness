export const AGENTS = {
  "Tempo Hawk": { emoji: "\u{1F985}", color: "#4A90D9", role: "Pace & Efficiency" },
  "Iron Curtain": { emoji: "\u{1F6E1}\uFE0F", color: "#D94A4A", role: "Defensive Zealot" },
  "Glass Cannon": { emoji: "\u{1F4A5}", color: "#FFB347", role: "Shooting & Explosiveness" },
  "Road Dog": { emoji: "\u{1F43A}", color: "#7B8D6F", role: "Old-School Scout" },
  "Whisper": { emoji: "\u{1F441}\uFE0F", color: "#9B59B6", role: "Intel & Intangibles" },
  "Oracle": { emoji: "\u{1F4DC}", color: "#E8D44D", role: "Historical Base Rates" },
  "The Conductor": { emoji: "\u{1F3BC}", color: "#FFFFFF", role: "Final Decision Maker" },
};

export function getAgent(name) {
  return AGENTS[name] || { emoji: "\u{1F916}", color: "#888", role: "Unknown" };
}
