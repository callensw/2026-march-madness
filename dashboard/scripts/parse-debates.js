#!/usr/bin/env node
/**
 * Parse all debate markdown files into structured JSON for the dashboard.
 * Run: node scripts/parse-debates.js
 */

import { readFileSync, readdirSync, writeFileSync } from 'fs';
import { join, basename } from 'path';

const DEBATES_DIR = join(import.meta.dirname, '../../debates');
const STRUCTURED_DATA = join(import.meta.dirname, '../../production_run_structured_data.json');
const OUTPUT = join(import.meta.dirname, '../src/data/debates.json');
const GAMES_OUTPUT = join(import.meta.dirname, '../src/data/games.json');

const AGENT_NAMES = ['TEMPO HAWK', 'IRON CURTAIN', 'GLASS CANNON', 'ROAD DOG', 'WHISPER', 'ORACLE', 'STREAK'];
const AGENT_EMOJIS = {
  'TEMPO HAWK': '🦅',
  'IRON CURTAIN': '🛡️',
  'GLASS CANNON': '💥',
  'ROAD DOG': '🐺',
  'WHISPER': '👁️',
  'ORACLE': '📜',
  'STREAK': '🔥',
  'THE CONDUCTOR': '🎼',
};

function parseDebateFile(filepath) {
  const content = readFileSync(filepath, 'utf-8');
  const filename = basename(filepath, '.md');

  // Extract header info
  const headerMatch = content.match(/^# 🏀 (.+)$/m);
  const header = headerMatch ? headerMatch[1] : filename;

  // Extract matchup info from header: "#1 Arizona vs #5 Vanderbilt — Championship Region, National Championship"
  const matchupMatch = header.match(/#(\d+)\s+(.+?)\s+vs\s+#(\d+)\s+(.+?)\s+—\s+(.+?),\s+(.+)/);
  let seedA, teamA, seedB, teamB, region, roundName;
  if (matchupMatch) {
    [, seedA, teamA, seedB, teamB, region, roundName] = matchupMatch;
  }

  const debate = {
    id: filename,
    header,
    seedA: seedA ? parseInt(seedA) : null,
    teamA: teamA?.trim() || null,
    seedB: seedB ? parseInt(seedB) : null,
    teamB: teamB?.trim() || null,
    region: region?.trim() || null,
    roundName: roundName?.trim() || null,
    round1: [],
    round2: [],
    devilsAdvocate: null,
    upsetWatch: null,
    conductor: null,
    voteTally: null,
    swarmVsVegas: null,
  };

  // Parse Round 1
  const r1Match = content.match(/## Round 1 — Independent Analysis\n([\s\S]*?)(?=## Round 2|### Devil's Advocate|### Upset Watch|---\n## 🎼)/);
  if (r1Match) {
    debate.round1 = parseAgentAnalyses(r1Match[1], false);
  }

  // Parse Round 2
  const r2Match = content.match(/## Round 2 — Cross-Examination\n([\s\S]*?)(?=### Upset Watch|### Devil's Advocate|### Swarm vs Vegas|---\n## 🎼)/);
  if (r2Match) {
    debate.round2 = parseAgentAnalyses(r2Match[1], true);
  }

  // Parse Devil's Advocate
  const daMatch = content.match(/### Devil's Advocate.*?\n([\s\S]*?)(?=### Swarm vs Vegas|### Upset Watch|---\n## 🎼)/);
  if (daMatch) {
    debate.devilsAdvocate = daMatch[1].trim();
  }

  // Parse Upset Watch
  const upsetMatch = content.match(/### Upset Watch\n\*\*Upset Score: ([\d.]+)\/100\*\*\s*\|\s*([\s\S]*?)(?=---|\n\n\n)/);
  if (upsetMatch) {
    debate.upsetWatch = {
      score: parseFloat(upsetMatch[1]),
      description: upsetMatch[2].trim(),
    };
  }

  // Parse Swarm vs Vegas
  const vegasMatch = content.match(/### Swarm vs Vegas\n\s*\*Swarm: (\d+)% on (.+?) \| Vegas implied: (\d+)% \| Delta: (.+?)\*/);
  if (vegasMatch) {
    debate.swarmVsVegas = {
      swarmPct: parseInt(vegasMatch[1]),
      swarmOn: vegasMatch[2],
      vegasPct: parseInt(vegasMatch[3]),
      delta: vegasMatch[4],
    };
  }

  // Parse Conductor
  const condMatch = content.match(/## 🎼 The Conductor — Final Analysis\n([\s\S]*?)(?=---\n### Specialist|---\n### Vote Tally|$)/);
  if (condMatch) {
    const condBlock = condMatch[1];

    const probMatch = condBlock.match(/Combined probability: (.+?) ([\d.]+) ± ([\d.]+)/);
    const pickMatch = condBlock.match(/\*\*PICK: (.+?)\*\*\s*\((.+?)\)/);
    const quoteMatch = condBlock.match(/🎼 \*\*THE CONDUCTOR\*\*: "(.+?)"/s);
    const keyFactorMatch = condBlock.match(/\*Key factor: (.+?)\*/);
    const mostWeightedMatch = condBlock.match(/\*Most weighted: (.+?)\*/);
    const dissentMatch = condBlock.match(/\*Dissent report: (.+?)\*/s);

    debate.conductor = {
      favoredTeam: probMatch ? probMatch[1] : null,
      probability: probMatch ? parseFloat(probMatch[2]) : null,
      uncertainty: probMatch ? parseFloat(probMatch[3]) : null,
      pick: pickMatch ? pickMatch[1] : null,
      confidence: pickMatch ? pickMatch[2] : null,
      quote: quoteMatch ? quoteMatch[1].replace(/\n/g, ' ') : null,
      keyFactor: keyFactorMatch ? keyFactorMatch[1] : null,
      mostWeighted: mostWeightedMatch ? mostWeightedMatch[1] : null,
      dissentReport: dissentMatch ? dissentMatch[1].replace(/\n/g, ' ') : null,
    };
  }

  // Parse Vote Tally
  const tallyMatch = content.match(/### Vote Tally\n([\s\S]*?)$/);
  if (tallyMatch) {
    const tallyBlock = tallyMatch[1];
    const votes = {};
    const voteLines = tallyBlock.match(/- \*\*(.+?)\*\*: (.+?) \((\d+) votes?\)/g);
    if (voteLines) {
      voteLines.forEach(line => {
        const m = line.match(/- \*\*(.+?)\*\*: (.+?) \((\d+) votes?\)/);
        if (m) {
          votes[m[1]] = {
            agents: m[2].split(', ').map(a => a.trim()),
            count: parseInt(m[3]),
          };
        }
      });
    }
    debate.voteTally = votes;
  }

  // Parse Specialist Vote line
  const specMatch = content.match(/### Specialist Vote: (.+)/);
  if (specMatch) {
    debate.specialistVote = specMatch[1];
  }

  // Parse CONDUCTOR AGREES/OVERRIDES
  const condAgreeMatch = content.match(/CONDUCTOR (AGREES|OVERRIDES): (.+?) \((\d+)%\)/);
  if (condAgreeMatch) {
    debate.conductorAction = condAgreeMatch[1];
    debate.conductorPick = condAgreeMatch[2];
    debate.conductorConfidence = parseInt(condAgreeMatch[3]);
  }

  return debate;
}

function parseAgentAnalyses(block, isRound2) {
  const analyses = [];

  // Split by agent emoji patterns
  const agentPattern = /(?:^|\n)(🦅|🛡️|💥|🐺|👁️|📜|🔥)\s+\*\*(.+?)\*\*/g;
  const matches = [...block.matchAll(agentPattern)];

  for (let i = 0; i < matches.length; i++) {
    const match = matches[i];
    const nextMatch = matches[i + 1];
    const startIdx = match.index;
    const endIdx = nextMatch ? nextMatch.index : block.length;
    const agentBlock = block.substring(startIdx, endIdx).trim();

    const emoji = match[1];
    let nameStr = match[2];

    // Extract model tag
    let model = 'claude';
    const modelMatch = nameStr.match(/`\[(\w+)\]`/);
    if (modelMatch) {
      model = modelMatch[1];
      nameStr = nameStr.replace(/\s*`\[.*?\]`/, '').trim();
    }

    // Extract position change for Round 2
    let positionChange = null;
    if (isRound2) {
      const posMatch = agentBlock.match(/\(position: (\w+)\)/);
      if (posMatch) {
        positionChange = posMatch[1];
      }
    }

    // Extract quote
    const quoteMatch = agentBlock.match(/"(.+?)"/s);
    const quote = quoteMatch ? quoteMatch[1].replace(/\n/g, ' ') : null;

    // Extract win probability
    const probMatch = agentBlock.match(/(?:Win probability|Updated probability): (.+?) ([\d.]+) ± ([\d.]+)/);
    let probability = null, uncertainty = null, favoredTeam = null;
    if (probMatch) {
      favoredTeam = probMatch[1];
      probability = parseFloat(probMatch[2]);
      uncertainty = parseFloat(probMatch[3]);
    }

    // Extract key stat
    const keyStatMatch = agentBlock.match(/\*Key stat: (.+?)\*/);
    const keyStat = keyStatMatch ? keyStatMatch[1] : null;

    // Extract disagreements and agreements (Round 2)
    let disagreesWith = null, agreesWith = null;
    if (isRound2) {
      const disagreeMatch = agentBlock.match(/\*Disagrees with:\*\s*(.+?)(?=\n\n|\n\s*\*Agrees)/s);
      if (disagreeMatch) disagreesWith = disagreeMatch[1].trim();

      const agreeMatch = agentBlock.match(/\*Agrees with:\*\s*(.+?)(?=\n\n|\n\s*")/s);
      if (agreeMatch) agreesWith = agreeMatch[1].trim();
    }

    // Clean name (remove position tag)
    const cleanName = nameStr.replace(/\s*\(position:.*?\)/, '').trim();

    analyses.push({
      emoji,
      name: cleanName,
      model,
      quote,
      favoredTeam,
      probability,
      uncertainty,
      keyStat,
      positionChange,
      disagreesWith,
      agreesWith,
    });
  }

  return analyses;
}

// Main
const files = readdirSync(DEBATES_DIR).filter(f => f.endsWith('.md')).sort();
console.log(`Parsing ${files.length} debate files...`);

const debates = {};
for (const file of files) {
  const filepath = join(DEBATES_DIR, file);
  const debate = parseDebateFile(filepath);
  debates[debate.id] = debate;
  console.log(`  ✓ ${debate.id} — ${debate.teamA} vs ${debate.teamB}`);
}

// Load structured data
const structuredData = JSON.parse(readFileSync(STRUCTURED_DATA, 'utf-8'));

// Write debates JSON
import { mkdirSync } from 'fs';
try { mkdirSync(join(import.meta.dirname, '../src/data'), { recursive: true }); } catch {}

writeFileSync(OUTPUT, JSON.stringify(debates, null, 2));
console.log(`\nWrote ${Object.keys(debates).length} debates to ${OUTPUT}`);

writeFileSync(GAMES_OUTPUT, JSON.stringify(structuredData, null, 2));
console.log(`Wrote structured game data to ${GAMES_OUTPUT}`);

console.log('\nDone!');
