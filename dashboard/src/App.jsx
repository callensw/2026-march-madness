import { useState, useEffect, useMemo, useRef } from 'react'
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
const ROUND_SHORT = { R64: 'R64', R32: 'R32', S16: 'S16', E8: 'E8', F4: 'F4', NCG: 'NCG' }

// Agent personality one-liners (editorial, no tech)
const AGENT_TAGLINES = {
  'Tempo Hawk': 'The clinical analyst who lives by pace and efficiency.',
  'Iron Curtain': 'The gruff defensive coordinator. If you can\'t stop them, you can\'t beat them.',
  'Glass Cannon': 'The hot take artist. One hot shooting night changes everything.',
  'Road Dog': 'The old-school scout. Experience and coaching pedigree win in March.',
  'Whisper': 'The insider. Injuries, travel fatigue, and the things nobody else sees.',
  'Oracle': 'The historian. Every upset has happened before.',
  'Streak': 'The momentum believer. What have you done LATELY?',
  'The Conductor': 'The final word. Math beats vibes.',
}

const AGENT_COLORS = {
  'Tempo Hawk': '#4FC3F7', 'Iron Curtain': '#EF5350', 'Glass Cannon': '#FFB74D',
  'Road Dog': '#81C784', 'Whisper': '#CE93D8', 'Oracle': '#FFF176',
  'Streak': '#FF8A65', 'The Conductor': '#FFFFFF',
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
  return game.winner === p.teamA ? { seed: p.seedA, team: p.teamA } : { seed: p.seedB, team: p.teamB }
}

function getLoserInfo(game) {
  const p = parseMatchup(game.matchup)
  if (!p) return { seed: 0, team: '' }
  return game.winner === p.teamA ? { seed: p.seedB, team: p.teamB } : { seed: p.seedA, team: p.teamA }
}

// ─── Precomputed Data ──────────────────────────────────────────────────────────
const games = gamesData.games
const r64Upsets = games.filter(g => g.round === 'R64' && isUpset(g))

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

const cinderellas = Object.entries(teamPaths)
  .filter(([, data]) => data.seed >= 5 && data.wins.length >= 2)
  .sort((a, b) => b[1].wins.length - a[1].wins.length)

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

const bracketByRegion = {}
games.forEach(g => {
  const region = (g.round === 'F4' || g.round === 'NCG') ? 'Final Four' : g.region
  if (!bracketByRegion[region]) bracketByRegion[region] = {}
  if (!bracketByRegion[region][g.round]) bracketByRegion[region][g.round] = []
  bracketByRegion[region][g.round].push(g)
})

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

// ─── Section: Hero ─────────────────────────────────────────────────────────────
function Hero({ champion, runnerUp, scrollTo }) {
  return (
    <section className="hero-bg min-h-[100dvh] flex flex-col items-center justify-center px-4 pt-16 pb-12 relative">
      <div className="relative z-10 flex flex-col items-center text-center w-full max-w-4xl mx-auto">
        {/* Main title */}
        <div className="animate-fade-up mb-4">
          <h1 className="font-display text-[clamp(3.5rem,12vw,10rem)] leading-[0.85] tracking-[0.04em] text-white uppercase">
            March Madness
          </h1>
          <h2 className="font-display text-[clamp(2.2rem,8vw,6.5rem)] leading-[0.85] tracking-[0.06em] gradient-text uppercase">
            AI War Room
          </h2>
        </div>

        <p className="animate-fade-up text-[#8899aa] text-base md:text-lg mb-10 font-body" style={{ animationDelay: '150ms' }}>
          8 AI Analysts Debated Every Game.<br className="md:hidden" />
          {' '}Here's Who They Think Wins.
        </p>

        {/* Championship VS graphic */}
        <div className="animate-fade-up w-full max-w-xl mb-12" style={{ animationDelay: '300ms' }}>
          <div className="relative bg-navy-800/60 border border-navy-600/40 rounded-2xl px-6 py-8 md:px-10 md:py-10">
            <div className="absolute -top-4 left-1/2 -translate-x-1/2">
              <span className="animate-crown inline-block text-4xl">🏆</span>
            </div>
            <div className="text-[10px] text-amber-400/80 font-headline font-semibold tracking-[0.3em] mb-5 uppercase">
              Champion Pick
            </div>

            <div className="flex items-center justify-center gap-3 md:gap-6">
              {/* Team A */}
              <div className="text-right flex-1">
                <div className="font-mono text-xs text-[#556677] mb-1">({champion.seed})</div>
                <div className="font-display text-3xl md:text-5xl text-white tracking-wider leading-none">
                  {champion.team.toUpperCase()}
                </div>
              </div>

              {/* VS */}
              <div className="flex flex-col items-center shrink-0">
                <div className="w-px h-6 bg-navy-600/60" />
                <div className="font-headline text-sm text-[#445566] font-bold my-1">VS</div>
                <div className="w-px h-6 bg-navy-600/60" />
              </div>

              {/* Team B */}
              <div className="text-left flex-1">
                <div className="font-mono text-xs text-[#556677] mb-1">({runnerUp.seed})</div>
                <div className="font-display text-3xl md:text-5xl text-[#556677] tracking-wider leading-none">
                  {runnerUp.team.toUpperCase()}
                </div>
              </div>
            </div>

            <div className="text-[#556677] text-xs font-mono mt-5">50% confidence</div>
          </div>
        </div>

        {/* Hero stat pills */}
        <div className="animate-fade-up grid grid-cols-2 md:grid-cols-4 gap-3 w-full max-w-lg md:max-w-2xl" style={{ animationDelay: '450ms' }}>
          {[
            { n: r64Upsets.length, l: 'Upsets Predicted', color: '#FF8A65' },
            { n: 63, l: 'Games Analyzed', color: '#4FC3F7' },
            { n: cinderellas.length, l: 'Cinderella Runs', color: '#CE93D8' },
            { n: totalFlips, l: 'Minds Changed', color: '#81C784' },
          ].map(s => (
            <div key={s.l} className="bg-navy-800/50 border border-navy-600/30 rounded-xl px-4 py-3 text-center">
              <div className="font-display text-3xl md:text-4xl" style={{ color: s.color }}>{s.n}</div>
              <div className="text-[#556677] text-[11px] font-medium mt-0.5">{s.l}</div>
            </div>
          ))}
        </div>

        {/* Scroll indicator */}
        <button
          onClick={() => scrollTo('bracket')}
          className="animate-fade-up mt-16 text-[#334455] hover:text-[#556677] transition-colors group"
          style={{ animationDelay: '700ms' }}
        >
          <span className="text-xs tracking-widest font-medium">EXPLORE THE BRACKET</span>
          <div className="mt-2 text-lg group-hover:translate-y-1 transition-transform">↓</div>
        </button>
      </div>
    </section>
  )
}

// ─── Section: Bracket ──────────────────────────────────────────────────────────
function BracketGameCard({ game, onClick }) {
  const p = parseMatchup(game.matchup)
  if (!p) return null
  const upset = isUpset(game)
  const isWinnerA = game.winner === p.teamA

  return (
    <button onClick={() => onClick(game)} className="bracket-game group relative text-left w-full">
      <div className={`team-row ${isWinnerA ? 'winner' : 'loser'}`}>
        <span className="seed">({p.seedA})</span>
        <span className="name">{p.teamA}</span>
        {isWinnerA && <span className="ml-auto text-emerald-400 text-[10px] font-bold">W</span>}
      </div>
      <div className="divider" />
      <div className={`team-row ${!isWinnerA ? 'winner' : 'loser'}`}>
        <span className="seed">({p.seedB})</span>
        <span className="name">{p.teamB}</span>
        {!isWinnerA && <span className="ml-auto text-emerald-400 text-[10px] font-bold">W</span>}
      </div>
      {upset && (
        <span className="absolute -top-2 -right-2 text-sm drop-shadow-lg" title="Upset!">🔥</span>
      )}
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
            <div className="text-[10px] text-[#445566] font-headline font-semibold tracking-[0.15em] text-center mb-2 uppercase">
              {ROUND_SHORT[rk]}
            </div>
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

function FinalFourCard({ game, onGameClick, label }) {
  const p = parseMatchup(game.matchup)
  if (!p) return null
  const upset = isUpset(game)
  const isWinnerA = game.winner === p.teamA

  return (
    <button
      onClick={() => onGameClick(game)}
      className="bg-navy-800/70 border border-navy-600/50 rounded-xl p-4 md:p-5 text-left hover:border-cyan-400/30 transition-all group w-full"
    >
      <div className="text-[10px] text-cyan-400/60 font-headline font-semibold tracking-[0.2em] mb-3 uppercase">{label}</div>
      <div className="space-y-1.5">
        <div className={`flex items-center gap-2 ${isWinnerA ? 'text-white' : 'text-[#445566]'}`}>
          <span className="font-mono text-[11px] w-6 text-right text-[#556677]">({p.seedA})</span>
          <span className="font-headline text-sm font-semibold tracking-wide">{p.teamA}</span>
          {isWinnerA && <span className="text-emerald-400 text-xs ml-auto">W</span>}
        </div>
        <div className={`flex items-center gap-2 ${!isWinnerA ? 'text-white' : 'text-[#445566]'}`}>
          <span className="font-mono text-[11px] w-6 text-right text-[#556677]">({p.seedB})</span>
          <span className="font-headline text-sm font-semibold tracking-wide">{p.teamB}</span>
          {!isWinnerA && <span className="text-emerald-400 text-xs ml-auto">W</span>}
        </div>
      </div>
      {upset && <div className="text-xs text-upset mt-2">🔥 Upset</div>}
      <div className="text-[10px] text-[#334455] font-mono mt-2">{game.vote_split}</div>
    </button>
  )
}

function BracketSection({ onGameClick }) {
  const [activeRegion, setActiveRegion] = useState('East')
  const [mobileRound, setMobileRound] = useState('R64')

  const f4Games = bracketByRegion['Final Four']?.F4 || []
  const ncgGame = (bracketByRegion['Final Four']?.NCG || [])[0]

  return (
    <section id="bracket" className="py-16 md:py-24 px-4">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-12">
          <h2 className="font-display text-[clamp(2rem,6vw,4.5rem)] text-white tracking-[0.04em] leading-none">
            THE BRACKET
          </h2>
          <p className="text-[#556677] text-sm mt-2 font-body">Click any game to see the full AI debate</p>
        </div>

        {/* Final Four + Championship — prominent center */}
        {ncgGame && (
          <div className="mb-14">
            {/* Championship */}
            <div className="max-w-md mx-auto mb-6">
              <FinalFourCard game={ncgGame} onGameClick={onGameClick} label="Championship" />
            </div>
            {/* F4 games */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-xl mx-auto">
              {f4Games.map(g => (
                <FinalFourCard key={g.game_number} game={g} onGameClick={onGameClick} label="Final Four" />
              ))}
            </div>
          </div>
        )}

        {/* Divider */}
        <div className="flex items-center gap-4 mb-8 max-w-2xl mx-auto">
          <div className="flex-1 h-px bg-navy-600/40" />
          <span className="text-[10px] text-[#445566] tracking-[0.2em] font-headline font-semibold">REGIONAL BRACKETS</span>
          <div className="flex-1 h-px bg-navy-600/40" />
        </div>

        {/* Region Tabs */}
        <div className="flex justify-center gap-1 mb-8">
          {REGIONS.map(r => (
            <button
              key={r}
              onClick={() => setActiveRegion(r)}
              className={`px-5 py-2 rounded-lg text-sm font-headline font-semibold tracking-wide transition-all ${
                activeRegion === r
                  ? 'bg-cyan-400/10 text-cyan-400 border border-cyan-400/30'
                  : 'text-[#556677] hover:text-[#8899aa] border border-transparent'
              }`}
            >
              {r}
            </button>
          ))}
        </div>

        {/* Desktop Bracket */}
        <div className="hidden md:block">
          <RegionBracket region={activeRegion} onGameClick={onGameClick} />
        </div>

        {/* Mobile: round tabs + vertical list */}
        <div className="md:hidden">
          <div className="flex gap-1 mb-4 overflow-x-auto scrollbar-none">
            {['R64', 'R32', 'S16', 'E8'].map(rk => (
              <button
                key={rk}
                onClick={() => setMobileRound(rk)}
                className={`px-3 py-1.5 rounded text-xs font-headline font-semibold whitespace-nowrap transition-all ${
                  mobileRound === rk
                    ? 'bg-cyan-400/15 text-cyan-400'
                    : 'text-[#556677]'
                }`}
              >
                {ROUND_SHORT[rk]}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-2">
            {(bracketByRegion[activeRegion]?.[mobileRound] || []).map(g => (
              <BracketGameCard key={g.game_number} game={g} onClick={onGameClick} />
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

// ─── Debate Viewer (Slide Panel) ───────────────────────────────────────────────
function PositionBadge({ change }) {
  const label = (change || '').toUpperCase()
  const config = {
    STRENGTHENED: { bg: 'rgba(129,199,132,0.12)', text: '#81C784', icon: '↑' },
    WEAKENED: { bg: 'rgba(255,183,77,0.12)', text: '#FFB74D', icon: '↓' },
    FLIPPED: { bg: 'rgba(239,83,80,0.12)', text: '#EF5350', icon: '↻' },
  }
  const c = config[label] || { bg: 'rgba(85,102,119,0.12)', text: '#556677', icon: '—' }

  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold"
      style={{ background: c.bg, color: c.text }}
    >
      {c.icon} {label || 'HELD'}
    </span>
  )
}

function AgentBubble({ entry, isRound2 = false }) {
  const agent = getAgent(entry.name)
  const color = AGENT_COLORS[agent.name] || agent.color || '#888'

  return (
    <div className="agent-bubble">
      <div className="flex items-start gap-3 mb-3">
        <div className="text-[28px] leading-none shrink-0 mt-0.5">{agent.emoji}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-headline text-sm font-semibold tracking-wide" style={{ color }}>{agent.name}</span>
            {isRound2 && entry.positionChange && <PositionBadge change={entry.positionChange} />}
          </div>
          <div className="text-[10px] text-[#556677] mt-0.5">{agent.role}</div>
        </div>
      </div>

      {entry.quote && (
        <p className="font-serif text-[13px] text-[#aabbcc] italic leading-relaxed mb-3">
          "{entry.quote}"
        </p>
      )}

      <div className="flex items-center justify-between gap-3">
        {entry.favoredTeam && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-white">{entry.favoredTeam}</span>
            {entry.probability && (
              <div className="flex items-center gap-1">
                <div className="w-16 h-1.5 bg-navy-700/80 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${Math.round(entry.probability * 100)}%`, backgroundColor: color }}
                  />
                </div>
                <span className="text-[10px] font-mono text-[#556677]">{Math.round(entry.probability * 100)}%</span>
              </div>
            )}
          </div>
        )}
      </div>

      {entry.keyStat && (
        <div className="text-[10px] text-[#445566] mt-2 pt-2 border-t border-navy-600/30 font-mono">
          {entry.keyStat}
        </div>
      )}

      {isRound2 && entry.disagreesWith && (
        <div className="text-[10px] text-red-400/60 mt-1 font-body">
          Challenges: {entry.disagreesWith}
        </div>
      )}
    </div>
  )
}

function DebatePanel({ game, onClose }) {
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
    <div className="debate-overlay fixed inset-0 z-50 bg-black/80 backdrop-blur-sm" onClick={onClose}>
      <div
        className="debate-panel absolute right-0 top-0 bottom-0 w-full max-w-3xl bg-[#080d18] border-l border-navy-600/40 overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="p-5 md:p-8">
          {/* Header */}
          <div className="flex justify-between items-start mb-8">
            <div>
              <div className="flex items-center gap-2 text-xs mb-2">
                <span className="text-cyan-400 font-headline font-semibold tracking-wide">{ROUND_LABELS[game.round]}</span>
                {game.region && <span className="text-[#445566]">·</span>}
                {game.region && <span className="text-[#445566]">{game.region}</span>}
                {upset && <span className="ml-1">🔥</span>}
              </div>
              <h3 className="font-display text-[clamp(1.5rem,4vw,2.5rem)] text-white tracking-wider leading-none">
                {game.matchup}
              </h3>
              <div className="flex items-center gap-3 mt-2">
                <span className="text-[#556677] font-mono text-xs">{game.vote_split}</span>
              </div>
            </div>
            <button onClick={onClose} className="text-[#445566] hover:text-white text-2xl leading-none p-2 -mr-2 -mt-2 transition-colors">
              ✕
            </button>
          </div>

          {debate ? (
            <>
              {/* Round 1 */}
              {debate.round1?.length > 0 && (
                <div className="mb-10">
                  <div className="flex items-center gap-3 mb-5">
                    <span className="font-display text-xl text-cyan-400">01</span>
                    <h4 className="font-headline text-sm font-semibold text-[#8899aa] tracking-[0.1em] uppercase">Independent Analysis</h4>
                    <div className="flex-1 h-px bg-navy-600/30" />
                  </div>
                  <div className="space-y-3 stagger-children">
                    {debate.round1.map((entry, i) => (
                      <div key={i} className="animate-fade-up"><AgentBubble entry={entry} /></div>
                    ))}
                  </div>
                </div>
              )}

              {/* Round 2 */}
              {debate.round2?.length > 0 && (
                <div className="mb-10">
                  <div className="flex items-center gap-3 mb-5">
                    <span className="font-display text-xl text-cyan-400">02</span>
                    <h4 className="font-headline text-sm font-semibold text-[#8899aa] tracking-[0.1em] uppercase">Cross-Examination</h4>
                    <div className="flex-1 h-px bg-navy-600/30" />
                  </div>
                  <div className="space-y-3 stagger-children">
                    {debate.round2.map((entry, i) => (
                      <div key={i} className="animate-fade-up"><AgentBubble entry={entry} isRound2 /></div>
                    ))}
                  </div>
                </div>
              )}

              {/* Verdict */}
              <div className="mb-6">
                <div className="flex items-center gap-3 mb-6">
                  <span className="text-3xl">🎼</span>
                  <h4 className="font-headline text-sm font-semibold text-[#8899aa] tracking-[0.1em] uppercase">The Verdict</h4>
                  <div className="flex-1 h-px bg-navy-600/30" />
                </div>

                {debate.conductor?.quote && (
                  <blockquote className="font-serif text-lg md:text-xl text-[#ccddee] italic leading-relaxed mb-6 pl-5 border-l-2 border-cyan-400/40">
                    "{debate.conductor.quote}"
                  </blockquote>
                )}

                {/* Vote visualization */}
                {debate.voteTally && (
                  <div className="flex flex-wrap gap-6 mb-6">
                    {Object.entries(debate.voteTally).map(([team, data]) => (
                      <div key={team} className="flex-1 min-w-[140px]">
                        <div className={`text-xs font-headline font-semibold tracking-wide mb-2 ${team === game.winner ? 'text-emerald-400' : 'text-[#445566]'}`}>
                          {team === game.winner && '✓ '}{team} ({data.count})
                        </div>
                        <div className="flex gap-2">
                          {data.agents.map(agentName => {
                            const a = getAgent(agentName)
                            return <span key={agentName} className="text-xl" title={agentName}>{a.emoji}</span>
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Winner card */}
                <div className="bg-navy-800/60 border border-navy-600/40 rounded-xl p-5 text-center">
                  <div className="font-display text-3xl md:text-4xl text-white tracking-wider">{game.winner}</div>
                  <div className="text-[#556677] text-sm font-mono mt-1">{game.combined_probability}</div>
                  {game.conductor_key_factor && (
                    <div className="text-cyan-400/50 text-xs mt-2 font-body">{game.conductor_key_factor}</div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="text-center py-16">
              <div className="text-5xl mb-6">🏀</div>
              <p className="text-[#556677] text-base mb-2 font-body">Quick consensus — no extended debate</p>
              <div className="bg-navy-800/60 border border-navy-600/40 rounded-xl inline-block px-8 py-5 mt-4">
                <div className="font-display text-3xl text-white tracking-wider">{game.winner}</div>
                <div className="text-[#556677] text-sm font-mono mt-1">{game.vote_split} · {game.confidence}</div>
                {game.conductor_key_factor && (
                  <div className="text-cyan-400/50 text-xs mt-2 font-body">{game.conductor_key_factor}</div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Section: Meet the Analysts ────────────────────────────────────────────────
function AgentCard({ agent, stats }) {
  const tagline = AGENT_TAGLINES[agent.name] || agent.personality
  const color = AGENT_COLORS[agent.name] || agent.color

  return (
    <div className="bg-navy-800/50 border border-navy-600/30 rounded-xl p-5 md:p-6 flex flex-col items-center text-center group hover:border-opacity-60 transition-all"
      style={{ '--agent-color': color }}
    >
      <div className="text-[56px] md:text-[64px] leading-none mb-3 group-hover:scale-110 transition-transform duration-300">
        {agent.emoji}
      </div>
      <h3 className="font-headline text-base md:text-lg font-semibold tracking-wide mb-1" style={{ color }}>
        {agent.name}
      </h3>
      <p className="font-serif text-[12px] md:text-[13px] text-[#778899] italic leading-relaxed mb-4 line-clamp-2">
        {tagline}
      </p>

      {stats && (
        <div className="flex gap-4 text-center mt-auto pt-3 border-t border-navy-600/30 w-full">
          <div className="flex-1">
            <div className="font-display text-lg text-[#EF5350]">{stats.flips}</div>
            <div className="text-[#445566] text-[10px]">flipped</div>
          </div>
          <div className="flex-1">
            <div className="font-display text-lg text-[#81C784]">{stats.strengthened}</div>
            <div className="text-[#445566] text-[10px]">held</div>
          </div>
          <div className="flex-1">
            <div className="font-display text-lg text-[#FFB74D]">{stats.weakened}</div>
            <div className="text-[#445566] text-[10px]">wavered</div>
          </div>
        </div>
      )}
    </div>
  )
}

function AnalystsSection() {
  return (
    <section id="analysts" className="py-16 md:py-24 px-4">
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-12">
          <h2 className="font-display text-[clamp(2rem,6vw,4.5rem)] text-white tracking-[0.04em] leading-none">
            MEET THE ANALYSTS
          </h2>
          <p className="text-[#556677] text-sm mt-2 font-body">8 AI personalities with unique perspectives on every game</p>
        </div>

        {/* Desktop: 4x2 grid. Mobile: horizontal scroll carousel */}
        <div className="hidden md:grid md:grid-cols-4 gap-4">
          {AGENTS.map(agent => (
            <AgentCard key={agent.name} agent={agent} stats={agentStats[agent.name.toUpperCase()]} />
          ))}
        </div>
        <div className="md:hidden flex gap-3 overflow-x-auto scrollbar-none pb-4 -mx-4 px-4 snap-x snap-mandatory">
          {AGENTS.map(agent => (
            <div key={agent.name} className="min-w-[240px] snap-start">
              <AgentCard agent={agent} stats={agentStats[agent.name.toUpperCase()]} />
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Section: Cinderella Watch ─────────────────────────────────────────────────
function CinderellaJourney({ team, data, onGameClick }) {
  const roundLabels = { R64: 'R64', R32: 'R32', S16: 'Sweet 16', E8: 'Elite 8', F4: 'Final Four', NCG: 'Title' }
  const farthestRound = data.eliminated ? ROUND_LABELS[data.eliminated.round] : 'Champion'

  let pullQuote = null
  for (const g of data.wins) {
    const d = findDebate(g)
    if (d?.conductor?.quote) { pullQuote = d.conductor.quote; break }
  }

  return (
    <div className="bg-navy-800/40 border border-navy-600/25 rounded-xl p-5 md:p-6 mb-4">
      <div className="flex items-start gap-3 mb-4">
        <div className="text-3xl shrink-0">🔮</div>
        <div>
          <h3 className="font-headline text-lg md:text-xl text-white font-semibold tracking-wide">
            ({data.seed}) {team}
          </h3>
          <p className="text-cyan-400/70 text-xs font-body">
            {data.wins.length} win{data.wins.length !== 1 ? 's' : ''} — Reached the {farthestRound}
          </p>
        </div>
      </div>

      {/* Journey path: horizontal timeline */}
      <div className="flex items-center gap-0 overflow-x-auto scrollbar-none pb-2 mb-4">
        {data.wins.map((g, i) => {
          const loser = getLoserInfo(g)
          return (
            <div key={g.game_number} className="flex items-center shrink-0">
              {i > 0 && <div className="journey-connector" />}
              <button onClick={() => onGameClick(g)} className="journey-node win">
                <span className="text-[#556677] font-mono text-[10px]">{roundLabels[g.round]}</span>
                <span className="font-body">({loser.seed}) {loser.team}</span>
              </button>
            </div>
          )
        })}
        {data.eliminated && (
          <>
            <div className="journey-connector" />
            <div className="journey-node loss shrink-0">
              <span className="text-[#556677] font-mono text-[10px]">{roundLabels[data.eliminated.round]}</span>
              <span className="font-body">{data.eliminated.winner}</span>
              <span className="text-[10px]">✗</span>
            </div>
          </>
        )}
      </div>

      {pullQuote && (
        <p className="font-serif text-xs text-[#667788] italic pl-4 border-l-2 border-navy-600/50 leading-relaxed">
          "{pullQuote.slice(0, 180)}{pullQuote.length > 180 ? '…' : ''}"
          <span className="not-italic text-[#445566]"> — The Conductor</span>
        </p>
      )}
    </div>
  )
}

function CinderellaSection({ onGameClick }) {
  return (
    <section id="cinderella" className="py-16 md:py-24 px-4 bg-navy-900/50">
      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-12">
          <h2 className="font-display text-[clamp(2rem,6vw,4.5rem)] text-white tracking-[0.04em] leading-none">
            CINDERELLA WATCH
          </h2>
          <p className="text-[#556677] text-sm mt-2 font-body">The underdogs who defied expectations</p>
        </div>

        {cinderellas.map(([team, data]) => (
          <CinderellaJourney key={team} team={team} data={data} onGameClick={onGameClick} />
        ))}
      </div>
    </section>
  )
}

// ─── Section: How It Works ─────────────────────────────────────────────────────
function HowItWorks() {
  const steps = [
    {
      icon: '🎯',
      title: 'Analyze',
      desc: '8 AI analysts independently study each matchup using different strategic lenses',
      detail: AGENTS.slice(0, 7).map(a => a.emoji).join('  '),
    },
    {
      icon: '🔥',
      title: 'Debate',
      desc: 'They challenge each other\'s arguments and can change their minds',
      detail: '↑ Held  ·  ↓ Wavered  ·  ↻ Flipped',
    },
    {
      icon: '📊',
      title: 'Decide',
      desc: 'A conductor synthesizes all arguments with weighted probability math',
      detail: 'P(win) = Σ wᵢ × pᵢ',
    },
  ]

  return (
    <section id="howItWorks" className="py-16 md:py-24 px-4">
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-14">
          <h2 className="font-display text-[clamp(2rem,6vw,4.5rem)] text-white tracking-[0.04em] leading-none">
            HOW IT WORKS
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 md:gap-8 mb-14">
          {steps.map((step, i) => (
            <div key={i} className="text-center">
              <div className="text-5xl mb-4">{step.icon}</div>
              <div className="font-display text-2xl text-white tracking-wider mb-2">{step.title.toUpperCase()}</div>
              <p className="text-[#778899] text-sm font-body leading-relaxed mb-4">{step.desc}</p>
              <div className="text-[#445566] text-xs font-mono">{step.detail}</div>
            </div>
          ))}
        </div>

        {/* Credibility */}
        <div className="bg-navy-800/50 border border-cyan-400/15 rounded-xl px-6 py-5 text-center">
          <p className="text-[#aabbcc] text-base md:text-lg font-body leading-relaxed">
            The AI predicted{' '}
            <span className="text-cyan-400 font-semibold">{r64Upsets.length} first-round upsets</span>
            {' '}— matching the exact historical average since 1985.
          </p>
        </div>
      </div>
    </section>
  )
}

// ─── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [selectedGame, setSelectedGame] = useState(null)

  const scrollTo = (id) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  const ncgGame = games.find(g => g.round === 'NCG')
  const champion = ncgGame ? getWinnerInfo(ncgGame) : { seed: 1, team: 'Arizona' }
  const runnerUp = ncgGame ? getLoserInfo(ncgGame) : { seed: 5, team: 'Vanderbilt' }

  return (
    <div className="min-h-screen bg-[#060b14] text-gray-200 font-body">
      {/* ── Sticky Nav ───────────────────────────────────────────────── */}
      <nav className="fixed top-0 left-0 right-0 z-40 bg-[#060b14]/90 backdrop-blur-md border-b border-navy-700/30">
        <div className="max-w-7xl mx-auto px-4 flex items-center gap-1 md:gap-3 h-11 overflow-x-auto scrollbar-none">
          <button onClick={() => scrollTo('hero')} className="font-display text-base tracking-[0.06em] text-cyan-400 whitespace-nowrap mr-3">
            🏀 WAR ROOM
          </button>
          {[
            { id: 'bracket', label: 'Bracket' },
            { id: 'analysts', label: 'Analysts' },
            { id: 'cinderella', label: 'Cinderellas' },
            { id: 'howItWorks', label: 'How It Works' },
          ].map(item => (
            <button
              key={item.id}
              onClick={() => scrollTo(item.id)}
              className="text-[11px] md:text-xs text-[#556677] hover:text-[#aabbcc] whitespace-nowrap transition-colors px-2 py-1 font-headline tracking-wide"
            >
              {item.label}
            </button>
          ))}
        </div>
      </nav>

      {/* ── Sections ─────────────────────────────────────────────────── */}
      <Hero champion={champion} runnerUp={runnerUp} scrollTo={scrollTo} />
      <BracketSection onGameClick={setSelectedGame} />
      <AnalystsSection />
      <CinderellaSection onGameClick={setSelectedGame} />
      <HowItWorks />

      {/* ── Footer ───────────────────────────────────────────────────── */}
      <footer className="py-10 px-4 border-t border-navy-700/20 text-center">
        <p className="text-[#334455] text-xs font-body">
          Built by Chase Allensworth · Six-Pillar Agent Framework
        </p>
        <p className="text-[#223344] text-[10px] mt-1">
          63 games debated · All picks are AI-generated predictions
        </p>
      </footer>

      {/* ── Debate Slide Panel ────────────────────────────────────────── */}
      <DebatePanel game={selectedGame} onClose={() => setSelectedGame(null)} />
    </div>
  )
}
