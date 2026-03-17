import { useState, useRef, useEffect, useMemo } from 'react'
import './App.css'
import gamesData from './data/games.json'
import debatesData from './data/debates.json'
import { AGENTS, getAgent } from './lib/agents'

// ─── Constants ─────────────────────────────────────────────────────────────────
const REGIONS = ['East', 'West', 'Midwest', 'South']
const ROUND_LABELS = {
  R64: 'Round of 64', R32: 'Round of 32', S16: 'Sweet 16',
  E8: 'Elite 8', F4: 'Final Four', NCG: 'Championship'
}
const ROUND_SHORT = {
  R64: 'R64', R32: 'R32', S16: 'S16', E8: 'E8', F4: 'F4', NCG: 'NCG'
}

// ─── Utility Functions ─────────────────────────────────────────────────────────
function parseMatchup(matchup) {
  const m = matchup.match(/#(\d+)\s+(.+?)\s+vs\s+#(\d+)\s+(.+)/)
  if (!m) return null
  return { seedA: +m[1], teamA: m[2].trim(), seedB: +m[3], teamB: m[4].trim() }
}

function isUpset(game) {
  const p = parseMatchup(game.matchup)
  if (!p) return false
  const winnerSeed = game.winner === p.teamA ? p.seedA : p.seedB
  const loserSeed = game.winner === p.teamA ? p.seedB : p.seedA
  return winnerSeed > loserSeed
}

function getWinnerInfo(game) {
  const p = parseMatchup(game.matchup)
  if (!p) return { seed: 0, team: game.winner }
  return game.winner === p.teamA
    ? { seed: p.seedA, team: p.teamA }
    : { seed: p.seedB, team: p.teamB }
}

function getLoserInfo(game) {
  const p = parseMatchup(game.matchup)
  if (!p) return { seed: 0, team: '' }
  return game.winner === p.teamA
    ? { seed: p.seedB, team: p.teamB }
    : { seed: p.seedA, team: p.teamA }
}

// ─── Precomputed Data ──────────────────────────────────────────────────────────
const games = gamesData.games
const metadata = gamesData.metadata

// R64 upsets (higher seed number wins)
const r64Upsets = games.filter(g => g.round === 'R64' && isUpset(g))

// Team paths through bracket
const teamPaths = {}
games.forEach(g => {
  const p = parseMatchup(g.matchup)
  if (!p) return
  const wInfo = getWinnerInfo(g)
  const lInfo = getLoserInfo(g)
  if (!teamPaths[g.winner]) teamPaths[g.winner] = { seed: wInfo.seed, wins: [], eliminated: null }
  teamPaths[g.winner].wins.push(g)
  if (!teamPaths[lInfo.team]) teamPaths[lInfo.team] = { seed: lInfo.seed, wins: [], eliminated: null }
  teamPaths[lInfo.team].eliminated = g
})

// Cinderella runs: teams seeded 5+ with 2+ wins, sorted by deepest run
const cinderellas = Object.entries(teamPaths)
  .filter(([, data]) => data.seed >= 5 && data.wins.length >= 2)
  .sort((a, b) => b[1].wins.length - a[1].wins.length)

// Agent stats from debates
const agentStats = {}
Object.values(debatesData).forEach(d => {
  ;(d.round2 || []).forEach(entry => {
    const name = entry.name
    if (!agentStats[name]) agentStats[name] = { flips: 0, strengthened: 0, weakened: 0, games: 0 }
    agentStats[name].games++
    const pc = (entry.positionChange || '').toUpperCase()
    if (pc === 'FLIPPED') agentStats[name].flips++
    else if (pc === 'STRENGTHENED') agentStats[name].strengthened++
    else if (pc === 'WEAKENED') agentStats[name].weakened++
  })
})
const totalFlips = Object.values(agentStats).reduce((sum, s) => sum + s.flips, 0)

// Bracket organized by region and round
const bracketByRegion = {}
games.forEach(g => {
  const region = (g.round === 'F4' || g.round === 'NCG') ? 'Final Four' : g.region
  if (!bracketByRegion[region]) bracketByRegion[region] = {}
  if (!bracketByRegion[region][g.round]) bracketByRegion[region][g.round] = []
  bracketByRegion[region][g.round].push(g)
})

// Debate lookup: match game to debate by team names
function findDebate(game) {
  const p = parseMatchup(game.matchup)
  if (!p) return null
  const gA = p.teamA.toLowerCase().replace(/[^a-z]/g, '')
  const gB = p.teamB.toLowerCase().replace(/[^a-z]/g, '')

  for (const [, debate] of Object.entries(debatesData)) {
    if (!debate.teamA || !debate.teamB) continue
    const dA = debate.teamA.toLowerCase().replace(/[^a-z]/g, '')
    const dB = debate.teamB.toLowerCase().replace(/[^a-z]/g, '')
    if ((dA.includes(gA) || gA.includes(dA)) && (dB.includes(gB) || gB.includes(dB))) return debate
    if ((dA.includes(gB) || gB.includes(dA)) && (dB.includes(gA) || gA.includes(dB))) return debate
  }
  // Fallback: match on winner name + round
  const roundMap = { R64: 'Round of 64', R32: 'Round of 32', S16: 'Sweet 16', E8: 'Elite 8', F4: 'Final Four', NCG: 'National Championship' }
  for (const [, debate] of Object.entries(debatesData)) {
    if (!debate.teamA) continue
    const rn = debate.roundName || ''
    if (rn.includes('Championship') && game.round === 'NCG') {
      if (debate.teamA.toLowerCase().includes(p.teamA.toLowerCase())) return debate
    }
    if (rn === roundMap[game.round]) {
      if (debate.teamA.toLowerCase().includes(p.teamA.toLowerCase())) return debate
    }
  }
  return null
}

// Signature descriptions for agents (no model names)
const SIGNATURE_STATS = {
  'Tempo Hawk': 'Possessions & pace mismatches',
  'Iron Curtain': 'Opponent FG% & defensive efficiency',
  'Glass Cannon': 'Three-point variance & hot shooting',
  'Road Dog': 'Senior leadership & coaching pedigree',
  'Whisper': 'Injuries, travel fatigue & hidden edges',
  'Oracle': 'Historical upset patterns since 1985',
  'Streak': 'Win streaks & conference tournament momentum',
  'The Conductor': 'Weighted probability synthesis',
}

// ─── Sub-Components ────────────────────────────────────────────────────────────

function HeroStat({ number, label }) {
  return (
    <div className="glass-card p-4 md:p-5 text-center">
      <div className="font-display text-4xl md:text-5xl text-cyan-400 stat-glow">{number}</div>
      <div className="text-gray-400 text-xs md:text-sm mt-1 leading-tight">{label}</div>
    </div>
  )
}

function BracketGameCard({ game, onClick, highlight = false }) {
  const p = parseMatchup(game.matchup)
  if (!p) return null
  const upset = isUpset(game)
  const isWinnerA = game.winner === p.teamA

  return (
    <button
      onClick={() => onClick(game)}
      className={`bracket-game-card group relative text-left transition-all hover:scale-[1.02] ${highlight ? 'ring-2 ring-cyan-400/50' : ''}`}
    >
      <div className={`team-row ${isWinnerA ? 'winner' : 'loser'}`}>
        <span className="seed">({p.seedA})</span>
        <span className="name">{p.teamA}</span>
        {isWinnerA && <span className="ml-auto text-emerald-400 text-xs font-bold">W</span>}
      </div>
      <div className={`team-row ${!isWinnerA ? 'winner' : 'loser'}`}>
        <span className="seed">({p.seedB})</span>
        <span className="name">{p.teamB}</span>
        {!isWinnerA && <span className="ml-auto text-emerald-400 text-xs font-bold">W</span>}
      </div>
      {upset && <span className="absolute -top-1.5 -right-1.5 text-sm" title="Upset!">🔥</span>}
    </button>
  )
}

function RegionBracket({ region, onGameClick }) {
  const rounds = bracketByRegion[region]
  if (!rounds) return null

  const roundKeys = ['R64', 'R32', 'S16', 'E8']
  return (
    <div className="bracket-grid">
      {roundKeys.map(rk => {
        const roundGames = rounds[rk] || []
        return (
          <div key={rk} className="bracket-round-col">
            <div className="text-[10px] text-gray-500 font-semibold tracking-widest text-center mb-2 uppercase">{ROUND_SHORT[rk]}</div>
            <div className="bracket-round-games">
              {roundGames.map(g => (
                <BracketGameCard key={g.game_number} game={g} onClick={onGameClick} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function FinalFourShowcase({ onGameClick }) {
  const f4Games = bracketByRegion['Final Four']?.F4 || []
  const ncgGame = (bracketByRegion['Final Four']?.NCG || [])[0]
  if (!ncgGame) return null

  const ncgParsed = parseMatchup(ncgGame.matchup)
  const champion = ncgGame.winner
  const championSeed = getWinnerInfo(ncgGame).seed

  return (
    <div className="mb-12">
      <div className="text-center mb-6">
        <div className="inline-block glass-card px-6 py-4 border-2 border-amber-400/30">
          <div className="text-xs text-amber-400 font-semibold tracking-widest mb-1">CHAMPIONSHIP</div>
          <div className="font-display text-2xl md:text-3xl text-white tracking-wider">{ncgGame.matchup}</div>
          <div className="text-gray-400 text-sm mt-1">Vote: {ncgGame.vote_split}</div>
          <button onClick={() => onGameClick(ncgGame)} className="mt-3 text-cyan-400 text-sm hover:underline">
            Read the debate →
          </button>
        </div>
      </div>

      <div className="flex flex-col md:flex-row items-center justify-center gap-4 md:gap-8">
        {f4Games.map(g => (
          <div key={g.game_number} className="glass-card p-4">
            <div className="text-xs text-cyan-400 font-semibold tracking-widest mb-2 text-center">FINAL FOUR</div>
            <BracketGameCard game={g} onClick={onGameClick} />
          </div>
        ))}
      </div>
    </div>
  )
}

function PositionBadge({ change }) {
  const label = (change || '').toUpperCase()
  const config = {
    STRENGTHENED: { bg: 'bg-emerald-400/15', text: 'text-emerald-400', border: 'border-emerald-400/30', icon: '↑' },
    WEAKENED: { bg: 'bg-amber-400/15', text: 'text-amber-400', border: 'border-amber-400/30', icon: '↓' },
    FLIPPED: { bg: 'bg-red-400/15', text: 'text-red-400', border: 'border-red-400/30', icon: '↻' },
  }
  const c = config[label] || { bg: 'bg-gray-400/15', text: 'text-gray-400', border: 'border-gray-400/30', icon: '—' }

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${c.bg} ${c.text} ${c.border}`}>
      {c.icon} {label || 'UNCHANGED'}
    </span>
  )
}

function ConfidenceBar({ probability, color }) {
  const pct = Math.round((probability || 0) * 100)
  return (
    <div className="mt-2">
      <div className="h-1.5 bg-navy-700 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color || '#4FC3F7' }}
        />
      </div>
      <div className="text-right text-[10px] text-gray-500 mt-0.5">{pct}%</div>
    </div>
  )
}

function AgentAnalysisCard({ entry, isRound2 = false }) {
  const agent = getAgent(entry.name)

  return (
    <div className="glass-card p-4 flex flex-col">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-2xl">{agent.emoji}</span>
        <div>
          <div className="font-semibold text-white text-sm">{agent.name}</div>
          <div className="text-[10px] text-gray-500">{agent.role}</div>
        </div>
        {isRound2 && entry.positionChange && (
          <div className="ml-auto">
            <PositionBadge change={entry.positionChange} />
          </div>
        )}
      </div>

      {entry.quote && (
        <p className="text-gray-300 text-sm italic mb-2 flex-1">"{entry.quote}"</p>
      )}

      {entry.favoredTeam && entry.probability && (
        <div className="text-xs text-gray-400">
          <span className="font-semibold text-white">{entry.favoredTeam}</span>
          <ConfidenceBar probability={entry.probability} color={agent.color} />
        </div>
      )}

      {entry.keyStat && (
        <div className="text-[10px] text-gray-500 mt-2 border-t border-navy-600/50 pt-2">
          📊 {entry.keyStat}
        </div>
      )}

      {isRound2 && entry.disagreesWith && (
        <div className="text-[10px] text-red-300/70 mt-2 border-t border-navy-600/50 pt-2">
          ⚔️ {entry.disagreesWith}
        </div>
      )}
    </div>
  )
}

function DebateModal({ game, onClose }) {
  const debate = useMemo(() => game ? findDebate(game) : null, [game])

  useEffect(() => {
    if (game) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [game])

  if (!game) return null
  const p = parseMatchup(game.matchup)
  const upset = isUpset(game)

  return (
    <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm overflow-y-auto" onClick={onClose}>
      <div className="max-w-5xl mx-auto px-4 py-6 md:py-10" onClick={e => e.stopPropagation()}>
        <div className="glass-card p-5 md:p-8 border border-navy-600/80">
          {/* Header */}
          <div className="flex justify-between items-start mb-6">
            <div>
              <div className="flex items-center gap-2 text-sm mb-1">
                <span className="text-cyan-400 font-semibold">{ROUND_LABELS[game.round]}</span>
                {game.region && <span className="text-gray-500">• {game.region}</span>}
                {upset && <span className="text-sm" title="Upset!">🔥 Upset</span>}
              </div>
              <h3 className="font-display text-2xl md:text-4xl text-white tracking-wider">{game.matchup}</h3>
              <p className="text-gray-400 text-sm mt-1">Vote: {game.vote_split}</p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-white text-3xl leading-none ml-4">×</button>
          </div>

          {debate ? (
            <>
              {/* Round 1 — Independent Analysis */}
              {debate.round1?.length > 0 && (
                <div className="mb-8">
                  <h4 className="font-display text-xl text-white tracking-wider mb-4 flex items-center gap-2">
                    <span className="text-cyan-400">01</span> Independent Analysis
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {debate.round1.map((entry, i) => (
                      <AgentAnalysisCard key={i} entry={entry} />
                    ))}
                  </div>
                </div>
              )}

              {/* Round 2 — Cross Examination */}
              {debate.round2?.length > 0 && (
                <div className="mb-8">
                  <h4 className="font-display text-xl text-white tracking-wider mb-4 flex items-center gap-2">
                    <span className="text-cyan-400">02</span> Cross-Examination
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {debate.round2.map((entry, i) => (
                      <AgentAnalysisCard key={i} entry={entry} isRound2 />
                    ))}
                  </div>
                </div>
              )}

              {/* The Verdict */}
              <div className="border-t-2 border-cyan-400/30 pt-6">
                <h4 className="font-display text-xl text-white tracking-wider mb-4 flex items-center gap-2">
                  <span className="text-3xl">🎼</span> The Verdict
                </h4>

                {debate.conductor?.quote && (
                  <blockquote className="text-lg md:text-xl text-gray-200 italic mb-6 pl-4 border-l-4 border-cyan-400/50 leading-relaxed">
                    "{debate.conductor.quote}"
                  </blockquote>
                )}

                {/* Vote visualization */}
                {debate.voteTally && (
                  <div className="flex flex-wrap gap-6 mb-6">
                    {Object.entries(debate.voteTally).map(([team, data]) => (
                      <div key={team} className="flex-1 min-w-[140px]">
                        <div className={`font-semibold text-sm mb-2 ${team === game.winner ? 'text-emerald-400' : 'text-gray-400'}`}>
                          {team === game.winner ? '✓ ' : ''}{team} ({data.count})
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {data.agents.map(agentName => {
                            const a = getAgent(agentName)
                            return (
                              <span key={agentName} className="text-xl" title={agentName}>{a.emoji}</span>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Conductor decision */}
                <div className={`glass-card p-4 text-center ${game.conductor_status?.includes('OVERRIDES') ? 'border border-amber-400/40' : 'border border-emerald-400/30'}`}>
                  {game.conductor_status?.includes('OVERRIDES') && (
                    <div className="text-amber-400 text-xs font-semibold tracking-widest mb-1">CONDUCTOR OVERRIDE</div>
                  )}
                  <div className="font-display text-2xl md:text-3xl text-white tracking-wider">
                    {game.winner}
                  </div>
                  <div className="text-gray-400 text-sm mt-1">
                    {debate.conductor?.confidence || game.combined_probability}
                  </div>
                  {game.conductor_key_factor && (
                    <div className="text-cyan-400/70 text-xs mt-2">Key factor: {game.conductor_key_factor}</div>
                  )}
                </div>
              </div>
            </>
          ) : (
            /* No debate found */
            <div className="text-center py-10">
              <div className="text-4xl mb-4">🏀</div>
              <p className="text-gray-400 text-lg mb-2">Quick consensus — no extended debate</p>
              <div className="glass-card inline-block px-6 py-4 mt-4">
                <div className="font-display text-2xl text-white tracking-wider">{game.winner}</div>
                <div className="text-gray-400 text-sm mt-1">{game.vote_split} • {game.confidence}</div>
                {game.conductor_key_factor && (
                  <div className="text-cyan-400/70 text-xs mt-2">{game.conductor_key_factor}</div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function AgentProfileCard({ agent, stats }) {
  const sig = SIGNATURE_STATS[agent.name]
  const totalChanges = stats ? stats.flips + stats.weakened : 0

  return (
    <div className="glass-card p-5 flex flex-col items-center text-center group hover:border-cyan-400/30 transition-all">
      <div className="text-5xl mb-3 group-hover:scale-110 transition-transform">{agent.emoji}</div>
      <h3 className="font-display text-lg tracking-wider text-white">{agent.name}</h3>
      <p className="text-cyan-400 text-xs font-semibold tracking-wider mb-2">{agent.role}</p>
      <p className="text-gray-400 text-xs leading-relaxed mb-4 line-clamp-3">{agent.personality}</p>

      {sig && (
        <div className="text-[10px] text-gray-500 mb-3">
          <span className="text-gray-400">Signature:</span> {sig}
        </div>
      )}

      {stats && (
        <div className="flex gap-4 text-center mt-auto pt-3 border-t border-navy-600/50 w-full">
          <div className="flex-1">
            <div className="text-red-400 font-bold text-sm">{stats.flips}</div>
            <div className="text-gray-500 text-[10px]">flipped</div>
          </div>
          <div className="flex-1">
            <div className="text-emerald-400 font-bold text-sm">{stats.strengthened}</div>
            <div className="text-gray-500 text-[10px]">held firm</div>
          </div>
          <div className="flex-1">
            <div className="text-amber-400 font-bold text-sm">{stats.weakened}</div>
            <div className="text-gray-500 text-[10px]">wavered</div>
          </div>
        </div>
      )}
    </div>
  )
}

function CinderellaCard({ team, data, onGameClick }) {
  const roundLabels = { R64: 'Rd 64', R32: 'Rd 32', S16: 'Sweet 16', E8: 'Elite 8', F4: 'Final 4', NCG: 'Title' }
  const farthestRound = data.eliminated
    ? ROUND_LABELS[data.eliminated.round]
    : 'Champion'

  // Find a quote about this team from a conductor analysis
  let pullQuote = null
  for (const g of data.wins) {
    const d = findDebate(g)
    if (d?.conductor?.quote) {
      pullQuote = d.conductor.quote
      break
    }
  }

  return (
    <div className="glass-card p-5 md:p-6 mb-4">
      <div className="flex items-start gap-4 mb-4">
        <div className="text-4xl">🔮</div>
        <div className="flex-1">
          <h3 className="font-display text-xl md:text-2xl text-white tracking-wider">
            ({data.seed}) {team}
          </h3>
          <p className="text-cyan-400 text-sm">
            {data.wins.length} win{data.wins.length !== 1 ? 's' : ''} — Reached the {farthestRound}
          </p>
        </div>
      </div>

      {/* Journey path */}
      <div className="flex flex-wrap gap-2 mb-4">
        {data.wins.map(g => {
          const loser = getLoserInfo(g)
          return (
            <button
              key={g.game_number}
              onClick={() => onGameClick(g)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-400/10 border border-emerald-400/30 text-emerald-400 text-xs hover:bg-emerald-400/20 transition-colors"
            >
              <span className="text-gray-500 font-semibold">{roundLabels[g.round]}</span>
              <span>beat ({loser.seed}) {loser.team}</span>
              <span className="text-gray-600">{g.vote_split}</span>
            </button>
          )
        })}
        {data.eliminated && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-400/10 border border-red-400/30 text-red-400 text-xs">
            <span className="text-gray-500 font-semibold">{roundLabels[data.eliminated.round]}</span>
            <span>lost to {data.eliminated.winner}</span>
          </div>
        )}
      </div>

      {/* Pull quote */}
      {pullQuote && (
        <p className="text-gray-400 text-sm italic border-l-2 border-gray-600 pl-3">
          "{pullQuote.slice(0, 200)}{pullQuote.length > 200 ? '...' : ''}"
          <span className="text-gray-600 not-italic"> — The Conductor</span>
        </p>
      )}
    </div>
  )
}

// ─── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [selectedGame, setSelectedGame] = useState(null)
  const [activeRegion, setActiveRegion] = useState('East')
  const [mobileRound, setMobileRound] = useState('R64')

  const scrollTo = (id) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  // Champion info
  const ncgGame = games.find(g => g.round === 'NCG')
  const champion = ncgGame ? getWinnerInfo(ncgGame) : { seed: 1, team: 'Arizona' }
  const runnerUp = ncgGame ? getLoserInfo(ncgGame) : { seed: 5, team: 'Vanderbilt' }

  return (
    <div className="min-h-screen bg-navy-900 text-gray-200">
      {/* ── Sticky Navigation ──────────────────────────────────────────── */}
      <nav className="fixed top-0 left-0 right-0 z-40 bg-navy-900/95 backdrop-blur-md border-b border-navy-700/50">
        <div className="max-w-7xl mx-auto px-4 flex items-center gap-1 md:gap-4 h-12 overflow-x-auto scrollbar-none">
          <button onClick={() => scrollTo('hero')} className="text-lg font-display tracking-wider text-cyan-400 whitespace-nowrap mr-2">
            🏀 AI WAR ROOM
          </button>
          {[
            { id: 'bracket', label: 'Bracket' },
            { id: 'agents', label: 'Analysts' },
            { id: 'cinderella', label: 'Cinderellas' },
            { id: 'howItWorks', label: 'How It Works' },
          ].map(item => (
            <button
              key={item.id}
              onClick={() => scrollTo(item.id)}
              className="text-xs md:text-sm text-gray-400 hover:text-white whitespace-nowrap transition-colors px-2 py-1"
            >
              {item.label}
            </button>
          ))}
        </div>
      </nav>

      {/* ── Hero Section ───────────────────────────────────────────────── */}
      <section id="hero" className="min-h-[100dvh] flex flex-col items-center justify-center px-4 pt-16 pb-12 text-center">
        <div className="mb-6 animate-fade-in">
          <h1 className="font-display text-5xl sm:text-6xl md:text-8xl lg:text-9xl tracking-wider text-white uppercase leading-none">
            March Madness
          </h1>
          <h2 className="font-display text-3xl sm:text-4xl md:text-6xl lg:text-7xl tracking-wider gradient-text uppercase leading-none mt-1">
            AI War Room
          </h2>
        </div>

        <p className="text-gray-400 text-base md:text-xl mb-8 max-w-xl animate-fade-in" style={{ animationDelay: '0.1s' }}>
          8 AI Analysts. 63 Games. Every Debate Recorded.
        </p>

        {/* Champion Banner */}
        <div className="glass-card px-6 md:px-10 py-5 md:py-6 mb-10 text-center border border-amber-400/20 animate-fade-in" style={{ animationDelay: '0.2s' }}>
          <div className="text-xs text-amber-400 font-semibold tracking-[0.2em] mb-2">🏆 CHAMPION PICK</div>
          <div className="font-display text-3xl sm:text-4xl md:text-6xl text-white tracking-wider">
            ({champion.seed}) {champion.team}
          </div>
          <div className="text-gray-400 mt-1">over ({runnerUp.seed}) {runnerUp.team}</div>
        </div>

        {/* Hero Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-5 max-w-2xl w-full animate-fade-in" style={{ animationDelay: '0.3s' }}>
          <HeroStat number={r64Upsets.length} label="upset picks in Round 1" />
          <HeroStat number={63} label="games analyzed" />
          <HeroStat number={cinderellas.length} label="Cinderella runs" />
          <HeroStat number={totalFlips} label="positions flipped" />
        </div>

        <div className="mt-14 text-gray-600 text-sm animate-bounce" style={{ animationDelay: '1s' }}>
          <button onClick={() => scrollTo('bracket')} className="hover:text-gray-400 transition-colors">
            ↓ Explore the bracket
          </button>
        </div>
      </section>

      {/* ── Bracket Section ────────────────────────────────────────────── */}
      <section id="bracket" className="py-12 md:py-20 px-4">
        <div className="max-w-7xl mx-auto">
          <h2 className="font-display text-3xl md:text-5xl text-white tracking-wider text-center mb-1">THE BRACKET</h2>
          <p className="text-gray-500 text-center mb-8 text-sm">Click any game to see the AI debate</p>

          {/* Final Four + Championship */}
          <FinalFourShowcase onGameClick={setSelectedGame} />

          {/* Region Tabs */}
          <div className="flex justify-center gap-1 md:gap-2 mb-6 flex-wrap">
            {REGIONS.map(r => (
              <button
                key={r}
                onClick={() => setActiveRegion(r)}
                className={`px-4 py-2 rounded-lg text-xs md:text-sm font-semibold transition-all ${
                  activeRegion === r
                    ? 'bg-cyan-400/20 text-cyan-400 border border-cyan-400/50'
                    : 'text-gray-500 hover:text-white border border-transparent'
                }`}
              >
                {r}
              </button>
            ))}
          </div>

          {/* Desktop Bracket */}
          <div className="hidden md:block">
            <RegionBracket region={activeRegion} onGameClick={setSelectedGame} />
          </div>

          {/* Mobile Bracket - round-by-round */}
          <div className="md:hidden">
            <div className="flex gap-1 mb-4 overflow-x-auto scrollbar-none">
              {['R64', 'R32', 'S16', 'E8'].map(rk => (
                <button
                  key={rk}
                  onClick={() => setMobileRound(rk)}
                  className={`px-3 py-1.5 rounded text-xs font-semibold whitespace-nowrap transition-all ${
                    mobileRound === rk
                      ? 'bg-cyan-400/20 text-cyan-400'
                      : 'text-gray-500'
                  }`}
                >
                  {ROUND_SHORT[rk]}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-1 gap-2">
              {(bracketByRegion[activeRegion]?.[mobileRound] || []).map(g => (
                <BracketGameCard key={g.game_number} game={g} onClick={setSelectedGame} />
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Meet the Analysts ──────────────────────────────────────────── */}
      <section id="agents" className="py-12 md:py-20 px-4 bg-navy-800/30">
        <div className="max-w-6xl mx-auto">
          <h2 className="font-display text-3xl md:text-5xl text-white tracking-wider text-center mb-1">MEET THE ANALYSTS</h2>
          <p className="text-gray-500 text-center mb-10 text-sm">8 AI personalities with unique perspectives on every game</p>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
            {AGENTS.map(agent => (
              <AgentProfileCard
                key={agent.name}
                agent={agent}
                stats={agentStats[agent.name.toUpperCase()]}
              />
            ))}
          </div>
        </div>
      </section>

      {/* ── Cinderella Watch ───────────────────────────────────────────── */}
      <section id="cinderella" className="py-12 md:py-20 px-4">
        <div className="max-w-4xl mx-auto">
          <h2 className="font-display text-3xl md:text-5xl text-white tracking-wider text-center mb-1">CINDERELLA WATCH</h2>
          <p className="text-gray-500 text-center mb-10 text-sm">The underdogs who defied expectations</p>

          {cinderellas.map(([team, data]) => (
            <CinderellaCard key={team} team={team} data={data} onGameClick={setSelectedGame} />
          ))}
        </div>
      </section>

      {/* ── How It Works ───────────────────────────────────────────────── */}
      <section id="howItWorks" className="py-12 md:py-20 px-4 bg-navy-800/30">
        <div className="max-w-4xl mx-auto text-center">
          <h2 className="font-display text-3xl md:text-5xl text-white tracking-wider mb-10">HOW IT WORKS</h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
            <div className="glass-card p-6">
              <div className="text-4xl mb-4">🧠</div>
              <h3 className="font-display text-lg text-white tracking-wider mb-2">STEP 1</h3>
              <p className="text-gray-400 text-sm mb-4">8 AI analysts independently analyze each game using different strategic lenses</p>
              <div className="flex justify-center gap-1 text-2xl flex-wrap">
                {AGENTS.slice(0, 7).map(a => (
                  <span key={a.name} title={a.name}>{a.emoji}</span>
                ))}
              </div>
            </div>

            <div className="glass-card p-6">
              <div className="text-4xl mb-4">⚔️</div>
              <h3 className="font-display text-lg text-white tracking-wider mb-2">STEP 2</h3>
              <p className="text-gray-400 text-sm mb-4">They debate each other and can change their minds — strengthening, weakening, or flipping positions</p>
              <div className="flex justify-center gap-3">
                <span className="text-emerald-400 text-xs font-semibold">↑ HELD</span>
                <span className="text-amber-400 text-xs font-semibold">↓ WAVERED</span>
                <span className="text-red-400 text-xs font-semibold">↻ FLIPPED</span>
              </div>
            </div>

            <div className="glass-card p-6">
              <div className="text-4xl mb-4">📊</div>
              <h3 className="font-display text-lg text-white tracking-wider mb-2">STEP 3</h3>
              <p className="text-gray-400 text-sm mb-4">A conductor synthesizes all arguments with weighted probability math — not simple vote counting</p>
              <div className="text-cyan-400 text-xs font-mono">P(win) = Σ wᵢ × pᵢ</div>
            </div>
          </div>

          {/* Credibility statement */}
          <div className="glass-card p-5 md:p-6 border border-cyan-400/20">
            <p className="text-base md:text-lg text-gray-200 leading-relaxed">
              The AI correctly predicted the historical upset rate —{' '}
              <span className="text-cyan-400 font-semibold">
                {r64Upsets.length} upsets out of 32 first-round games
              </span>
              , matching the 7–10 expected range since 1985.
            </p>
          </div>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <footer className="py-8 px-4 border-t border-navy-700/50 text-center">
        <p className="text-gray-600 text-xs">
          Built with Claude & Gemini • 63 games debated • All picks are AI-generated predictions
        </p>
      </footer>

      {/* ── Debate Modal ───────────────────────────────────────────────── */}
      <DebateModal game={selectedGame} onClose={() => setSelectedGame(null)} />
    </div>
  )
}
