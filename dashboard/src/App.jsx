import { useState, useRef } from 'react'
import './App.css'
import gamesData from './data/games.json'
import debatesData from './data/debates.json'
import { AGENTS, getAgent } from './lib/agents'

const NAV_ITEMS = [
  { id: 'hero', label: 'Home' },
  { id: 'bracket', label: 'Bracket' },
  { id: 'agents', label: 'Agents' },
  { id: 'cinderella', label: 'Cinderellas' },
  { id: 'calibration', label: 'Calibration' },
  { id: 'howItWorks', label: 'How It Works' },
]

// Bracket structure: map game IDs to bracket positions
const REGIONS = ['East', 'West', 'Midwest', 'South']
const ROUND_LABELS = { R64: 'Round of 64', R32: 'Round of 32', S16: 'Sweet 16', E8: 'Elite 8', F4: 'Final Four', NCG: 'Championship' }

function getRoundFromId(id) {
  if (id.startsWith('NCG_')) return 'NCG'
  if (id.startsWith('F4_')) return 'F4'
  if (id.startsWith('E8_')) return 'E8'
  if (id.startsWith('S16_')) return 'S16'
  if (id.startsWith('R32_')) return 'R32'
  if (id.startsWith('R64_')) return 'R64'
  return 'R64'
}

function getGameRegion(gameNum) {
  const game = gamesData.games.find(g => g.game_number === gameNum)
  return game?.region || ''
}

// Build game lookup from structured data
const gamesByNumber = {}
gamesData.games.forEach(g => { gamesByNumber[g.game_number] = g })

// Build debate lookup by matching team names + round
function findDebate(matchup, round) {
  // First pass: exact match on both team names
  for (const [id, debate] of Object.entries(debatesData)) {
    if (debate.teamA && debate.teamB) {
      const m = matchup.toLowerCase()
      if (m.includes(debate.teamA.toLowerCase()) && m.includes(debate.teamB.toLowerCase())) {
        return { id, ...debate }
      }
    }
  }

  // Second pass: match by round prefix + at least one team name
  // This handles cases where structured data has different matchup opponents
  // than what was actually debated (bracket path discrepancies)
  const roundPrefix = round + '_'
  const teams = matchup.match(/#\d+\s+(.+?)\s+vs\s+#\d+\s+(.+)/)
  if (teams) {
    const [, tA, tB] = teams
    for (const [id, debate] of Object.entries(debatesData)) {
      if (!id.startsWith(roundPrefix)) continue
      if (debate.teamA && debate.teamB) {
        const dTeams = [debate.teamA.toLowerCase(), debate.teamB.toLowerCase()]
        if (dTeams.includes(tA.toLowerCase()) || dTeams.includes(tB.toLowerCase())) {
          return { id, ...debate }
        }
      }
    }
  }

  return null
}

// Group games by round and region
const gamesByRound = {}
gamesData.games.forEach(g => {
  const r = g.round
  if (!gamesByRound[r]) gamesByRound[r] = []
  gamesByRound[r].push(g)
})

export default function App() {
  const [activeSection, setActiveSection] = useState('hero')
  const [selectedGame, setSelectedGame] = useState(null)
  const [selectedRegion, setSelectedRegion] = useState('East')
  const [showFinalRounds, setShowFinalRounds] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const sectionRefs = useRef({})

  const scrollTo = (id) => {
    setMobileMenuOpen(false)
    sectionRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="min-h-screen bg-navy-900">
      {/* Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-navy-900/95 backdrop-blur-md border-b border-navy-600/30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-2">
              <span className="text-xl">🏀</span>
              <span className="font-display text-lg font-bold tracking-wide text-white hidden sm:block">AGENT SWARM</span>
            </div>
            <div className="hidden md:flex items-center gap-1">
              {NAV_ITEMS.map(item => (
                <button
                  key={item.id}
                  onClick={() => scrollTo(item.id)}
                  className="px-3 py-1.5 text-sm font-medium text-gray-400 hover:text-cyan-400 transition-colors rounded-lg hover:bg-navy-700/50"
                >
                  {item.label}
                </button>
              ))}
            </div>
            <button
              className="md:hidden text-gray-400 p-2"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" />
              </svg>
            </button>
          </div>
        </div>
        {mobileMenuOpen && (
          <div className="md:hidden bg-navy-800 border-t border-navy-600/30 p-4 space-y-2">
            {NAV_ITEMS.map(item => (
              <button
                key={item.id}
                onClick={() => scrollTo(item.id)}
                className="block w-full text-left px-3 py-2 text-sm text-gray-300 hover:text-cyan-400 rounded"
              >
                {item.label}
              </button>
            ))}
          </div>
        )}
      </nav>

      <div className="pt-14">
        {/* HERO SECTION */}
        <section ref={el => sectionRefs.current.hero = el} className="relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-b from-cyan-400/5 via-transparent to-transparent" />
          <div className="absolute inset-0" style={{
            backgroundImage: 'radial-gradient(circle at 50% 0%, rgba(79,195,247,0.08) 0%, transparent 60%)',
          }} />
          <div className="relative max-w-7xl mx-auto px-4 sm:px-6 pt-16 pb-12 sm:pt-24 sm:pb-16 text-center">
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-cyan-400/10 border border-cyan-400/20 text-cyan-400 text-xs font-semibold tracking-wider uppercase mb-6">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              2026 NCAA Tournament
            </div>
            <h1 className="font-display text-4xl sm:text-6xl lg:text-7xl font-bold tracking-tight text-white mb-3">
              March Madness<br />
              <span className="gradient-text">Agent Swarm</span>
            </h1>
            <p className="text-lg sm:text-xl text-gray-400 max-w-2xl mx-auto mb-10">
              8 AI Agents Debate Every NCAA Tournament Game
            </p>

            {/* Champion callout */}
            <div className="glass-card inline-block px-8 py-5 mb-10">
              <div className="text-xs text-gray-500 uppercase tracking-widest mb-1">Predicted Champion</div>
              <div className="font-display text-3xl sm:text-4xl font-bold text-white">
                🏆 #1 Arizona
              </div>
              <div className="text-sm text-gray-400 mt-1">
                over #5 Vanderbilt &middot; 4-3 vote &middot; 53% confidence
              </div>
            </div>

            {/* Stats bar */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 max-w-5xl mx-auto">
              {[
                { label: 'Games', value: '63', sub: 'debated' },
                { label: 'R64 Upsets', value: '8/32', sub: 'called' },
                { label: 'API Calls', value: '881', sub: 'total' },
                { label: 'Cost', value: '$26.84', sub: 'total' },
                { label: 'Groupthink', value: '21%', sub: '13 unanimous' },
                { label: 'Overrides', value: '6', sub: 'conductor' },
              ].map((stat, i) => (
                <div key={i} className="glass-card px-4 py-3 text-center">
                  <div className="text-[10px] text-gray-500 uppercase tracking-wider">{stat.label}</div>
                  <div className="font-mono text-xl sm:text-2xl font-bold text-white mt-0.5">{stat.value}</div>
                  <div className="text-[10px] text-gray-600">{stat.sub}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* BRACKET SECTION */}
        <section ref={el => sectionRefs.current.bracket = el} className="max-w-7xl mx-auto px-4 sm:px-6 py-12">
          <h2 className="font-display text-3xl sm:text-4xl font-bold text-white mb-2">The Bracket</h2>
          <p className="text-gray-500 mb-6">Click any game to read the full agent debate</p>

          {/* Region tabs + Final Rounds */}
          <div className="flex flex-wrap items-center gap-2 mb-6">
            {REGIONS.map(r => (
              <button
                key={r}
                onClick={() => { setSelectedRegion(r); setShowFinalRounds(false); setSelectedGame(null) }}
                className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                  !showFinalRounds && selectedRegion === r
                    ? 'bg-cyan-400/15 text-cyan-400 border border-cyan-400/30'
                    : 'bg-navy-800 text-gray-400 border border-navy-600/30 hover:text-gray-200'
                }`}
              >
                {r}
              </button>
            ))}
            <div className="w-px h-6 bg-navy-600/50 mx-1 hidden sm:block" />
            <button
              onClick={() => { setShowFinalRounds(true); setSelectedGame(null) }}
              className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                showFinalRounds
                  ? 'bg-cyan-400/15 text-cyan-400 border border-cyan-400/30'
                  : 'bg-navy-800 text-gray-400 border border-navy-600/30 hover:text-gray-200'
              }`}
            >
              Final Four + Championship
            </button>
          </div>

          {/* Bracket Grid */}
          {showFinalRounds ? (
            <FinalRoundsView onSelectGame={setSelectedGame} />
          ) : (
            <RegionBracket region={selectedRegion} onSelectGame={setSelectedGame} />
          )}

          {/* Debate Modal */}
          {selectedGame && (
            <DebateTranscript game={selectedGame} onClose={() => setSelectedGame(null)} />
          )}
        </section>

        {/* AGENT PROFILES */}
        <section ref={el => sectionRefs.current.agents = el} className="max-w-7xl mx-auto px-4 sm:px-6 py-12">
          <h2 className="font-display text-3xl sm:text-4xl font-bold text-white mb-2">The Panel</h2>
          <p className="text-gray-500 mb-8">7 specialist agents + 1 conductor, each with a unique analytical lens</p>
          <AgentProfiles />
        </section>

        {/* CINDERELLA TRACKER */}
        <section ref={el => sectionRefs.current.cinderella = el} className="max-w-7xl mx-auto px-4 sm:px-6 py-12">
          <h2 className="font-display text-3xl sm:text-4xl font-bold text-white mb-2">Cinderella Tracker</h2>
          <p className="text-gray-500 mb-8">Upset runs and bracket busters</p>
          <CinderellaTracker onSelectGame={setSelectedGame} />
        </section>

        {/* CALIBRATION REPORT */}
        <section ref={el => sectionRefs.current.calibration = el} className="max-w-7xl mx-auto px-4 sm:px-6 py-12">
          <h2 className="font-display text-3xl sm:text-4xl font-bold text-white mb-2">Calibration Report</h2>
          <p className="text-gray-500 mb-8">R64 upset frequency vs historical expectations</p>
          <CalibrationChart />
        </section>

        {/* HOW IT WORKS */}
        <section ref={el => sectionRefs.current.howItWorks = el} className="max-w-7xl mx-auto px-4 sm:px-6 py-12 pb-24">
          <h2 className="font-display text-3xl sm:text-4xl font-bold text-white mb-2">How It Works</h2>
          <p className="text-gray-500 mb-8">Multi-round debate architecture with cross-examination</p>
          <HowItWorks />
        </section>

        {/* Footer */}
        <footer className="border-t border-navy-600/30 py-8 text-center text-gray-600 text-sm">
          <p>Built with Claude Sonnet 4 + Gemini 2.5 Flash &middot; 881 API calls &middot; $26.84 total cost</p>
          <p className="mt-1">March Madness Agent Swarm 2026</p>
        </footer>
      </div>
    </div>
  )
}

/* ==================== BRACKET COMPONENTS ==================== */

function RegionBracket({ region, onSelectGame }) {
  const regionGames = gamesData.games.filter(g => g.region === region)
  const rounds = ['R64', 'R32', 'S16', 'E8']
  const gamesByRd = {}
  rounds.forEach(r => {
    gamesByRd[r] = regionGames.filter(g => g.round === r)
  })

  return (
    <div className="overflow-x-auto pb-4">
      <div className="min-w-[900px] grid grid-cols-4 gap-4">
        {rounds.map(round => (
          <div key={round} className="space-y-2">
            <div className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-3 text-center">
              {ROUND_LABELS[round]}
            </div>
            <div className={`space-y-2 flex flex-col ${
              round === 'R32' ? 'justify-around py-4' :
              round === 'S16' ? 'justify-around py-12' :
              round === 'E8' ? 'justify-center' : ''
            }`} style={{ minHeight: round === 'R64' ? 'auto' : gamesByRd.R64.length * 58 }}>
              {gamesByRd[round]?.map((game, i) => (
                <GameCard key={game.game_number} game={game} onClick={() => onSelectGame(game)} compact />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function FinalRoundsView({ onSelectGame }) {
  const f4Games = gamesData.games.filter(g => g.round === 'F4')
  const ncgGames = gamesData.games.filter(g => g.round === 'NCG')

  return (
    <div className="space-y-8">
      <div>
        <div className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-3">Final Four</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {f4Games.map(game => (
            <GameCard key={game.game_number} game={game} onClick={() => onSelectGame(game)} />
          ))}
        </div>
      </div>
      <div>
        <div className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-3">National Championship</div>
        <div className="max-w-lg mx-auto">
          {ncgGames.map(game => (
            <GameCard key={game.game_number} game={game} onClick={() => onSelectGame(game)} featured />
          ))}
        </div>
      </div>
    </div>
  )
}

function GameCard({ game, onClick, compact, featured }) {
  const matchup = game.matchup || ''
  const teams = matchup.match(/#(\d+)\s+(.+?)\s+vs\s+#(\d+)\s+(.+)/)
  const seedA = teams ? parseInt(teams[1]) : null
  const teamA = teams ? teams[2] : '?'
  const seedB = teams ? parseInt(teams[3]) : null
  const teamB = teams ? teams[4] : '?'

  const isUpset = game.upset_watch || (game.winner && seedA && seedB && (
    (game.winner === teamA && seedA > seedB) ||
    (game.winner === teamB && seedB > seedA)
  ))

  const isOverride = game.conductor_status?.includes('OVERRIDES')
  const voteParts = game.vote_split?.match(/(\d+)-(\d+)/)
  const voteA = voteParts ? parseInt(voteParts[1]) : 0
  const voteB = voteParts ? parseInt(voteParts[2]) : 0

  const winnerIsA = game.winner === teamA
  const winnerIsB = game.winner === teamB

  return (
    <button
      onClick={onClick}
      className={`w-full text-left glass-card hover:border-cyan-400/40 transition-all cursor-pointer group ${
        featured ? 'p-5 border-2 border-cyan-400/20' : compact ? 'p-2.5' : 'p-4'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className={`flex items-center gap-2 ${compact ? 'text-xs' : 'text-sm'}`}>
            <span className={`font-mono text-gray-500 ${compact ? 'w-5' : 'w-6'} text-right shrink-0`}>{seedA}</span>
            <span className={`font-semibold truncate ${winnerIsA ? 'text-white' : 'text-gray-500'}`}>{teamA}</span>
            {winnerIsA && <span className="text-cyan-400 text-xs">✓</span>}
          </div>
          <div className={`flex items-center gap-2 mt-0.5 ${compact ? 'text-xs' : 'text-sm'}`}>
            <span className={`font-mono text-gray-500 ${compact ? 'w-5' : 'w-6'} text-right shrink-0`}>{seedB}</span>
            <span className={`font-semibold truncate ${winnerIsB ? 'text-white' : 'text-gray-500'}`}>{teamB}</span>
            {winnerIsB && <span className="text-cyan-400 text-xs">✓</span>}
          </div>
        </div>
        <div className="text-right shrink-0 flex flex-col items-end gap-1">
          {game.vote_split && (
            <span className={`font-mono text-[10px] ${compact ? '' : 'text-xs'} text-gray-500`}>{game.vote_split}</span>
          )}
          <div className="flex items-center gap-1">
            {isUpset && <span className="upset-badge text-[9px]">UPSET</span>}
            {isOverride && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[9px] font-semibold bg-purple-400/15 text-purple-400 border border-purple-400/30">
                OVERRIDE
              </span>
            )}
          </div>
        </div>
      </div>
      {!compact && game.conductor_key_factor && (
        <div className="mt-2 text-xs text-gray-500 line-clamp-1 group-hover:text-gray-400 transition-colors">
          {game.conductor_key_factor}
        </div>
      )}
    </button>
  )
}

/* ==================== DEBATE TRANSCRIPT ==================== */

function DebateTranscript({ game, onClose }) {
  const debate = findDebate(game.matchup, game.round)
  const [activeTab, setActiveTab] = useState('round1')

  const matchup = game.matchup || ''
  const teams = matchup.match(/#(\d+)\s+(.+?)\s+vs\s+#(\d+)\s+(.+)/)
  const seedA = teams ? parseInt(teams[1]) : null
  const teamA = teams ? teams[2] : '?'
  const seedB = teams ? parseInt(teams[3]) : null
  const teamB = teams ? teams[4] : '?'

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-16 sm:pt-20 overflow-y-auto" onClick={onClose}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
      <div
        className="relative bg-navy-900 border border-navy-600/50 rounded-2xl w-full max-w-3xl shadow-2xl animate-fade-in mb-8"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 bg-navy-900/95 backdrop-blur-md border-b border-navy-600/30 rounded-t-2xl px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">
                {ROUND_LABELS[game.round] || game.round} &middot; {game.region}
              </div>
              <h3 className="font-display text-xl sm:text-2xl font-bold text-white">
                #{seedA} {teamA} vs #{seedB} {teamB}
              </h3>
            </div>
            <button onClick={onClose} className="text-gray-500 hover:text-white p-2 -mr-2 transition-colors">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" />
              </svg>
            </button>
          </div>

          {/* Winner banner */}
          {game.winner && (
            <div className="mt-3 flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2 bg-cyan-400/10 border border-cyan-400/20 rounded-lg px-3 py-1.5">
                <span className="text-cyan-400 text-xs font-semibold">PICK</span>
                <span className="text-white font-bold">{game.winner}</span>
                <span className="font-mono text-xs text-gray-400">{game.vote_split}</span>
              </div>
              {game.upset_watch && <span className="upset-badge">UPSET {game.upset_score && `(${game.upset_score})`}</span>}
              {game.conductor_status?.includes('OVERRIDES') && (
                <span className="inline-flex items-center px-2 py-1 rounded-lg text-xs font-semibold bg-purple-400/10 text-purple-400 border border-purple-400/20">
                  CONDUCTOR OVERRIDE
                </span>
              )}
            </div>
          )}
        </div>

        {/* Tab navigation */}
        {debate && (
          <div className="flex border-b border-navy-600/30 px-6 overflow-x-auto">
            {[
              { id: 'round1', label: 'Round 1', count: debate.round1?.length },
              { id: 'round2', label: 'Round 2', count: debate.round2?.length },
              { id: 'verdict', label: 'Verdict' },
            ].filter(tab => tab.id !== 'round2' || debate.round2?.length > 0).map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                  activeTab === tab.id
                    ? 'border-cyan-400 text-cyan-400'
                    : 'border-transparent text-gray-500 hover:text-gray-300'
                }`}
              >
                {tab.label}
                {tab.count != null && <span className="ml-1 text-xs text-gray-600">({tab.count})</span>}
              </button>
            ))}
          </div>
        )}

        {/* Content */}
        <div className="px-6 py-5 max-h-[65vh] overflow-y-auto space-y-4">
          {!debate ? (
            <div className="text-center py-12 text-gray-500">
              <p>Debate transcript not available for this game.</p>
              {game.conductor_key_factor && (
                <p className="mt-4 text-sm text-gray-400">Key factor: {game.conductor_key_factor}</p>
              )}
            </div>
          ) : activeTab === 'round1' ? (
            <>
              <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Independent Analysis</div>
              {debate.round1.map((agent, i) => (
                <AgentCard key={i} agent={agent} teamA={teamA} teamB={teamB} />
              ))}
              {debate.devilsAdvocate && (
                <div className="glass-card p-4 border-l-4 border-amber-500/50">
                  <div className="text-xs text-amber-400 font-semibold uppercase tracking-wider mb-2">Devil's Advocate (unanimous trigger)</div>
                  <div className="text-sm text-gray-300">{debate.devilsAdvocate}</div>
                </div>
              )}
              {debate.swarmVsVegas && (
                <div className="glass-card p-4">
                  <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">Swarm vs Vegas</div>
                  <div className="flex items-center gap-4 text-sm">
                    <div>
                      <span className="text-gray-400">Swarm:</span>{' '}
                      <span className="font-mono font-bold text-white">{debate.swarmVsVegas.swarmPct}%</span>
                      <span className="text-gray-500 ml-1">on {debate.swarmVsVegas.swarmOn}</span>
                    </div>
                    <div className="text-gray-600">|</div>
                    <div>
                      <span className="text-gray-400">Vegas:</span>{' '}
                      <span className="font-mono font-bold text-white">{debate.swarmVsVegas.vegasPct}%</span>
                    </div>
                    <div className="text-gray-600">|</div>
                    <div className="text-gray-400">{debate.swarmVsVegas.delta}</div>
                  </div>
                </div>
              )}
            </>
          ) : activeTab === 'round2' ? (
            <>
              <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Cross-Examination</div>
              {debate.round2.map((agent, i) => (
                <AgentCard key={i} agent={agent} teamA={teamA} teamB={teamB} isRound2 />
              ))}
              {debate.upsetWatch && (
                <div className="glass-card p-4 border-l-4 border-orange-500/50">
                  <div className="text-xs text-orange-400 font-semibold uppercase tracking-wider mb-1">
                    Upset Watch — Score: {debate.upsetWatch.score}/100
                  </div>
                  <div className="text-sm text-gray-400">{debate.upsetWatch.description}</div>
                </div>
              )}
            </>
          ) : (
            /* Verdict tab */
            <>
              {debate.conductor && (
                <div className="space-y-4">
                  {/* Conductor card */}
                  <div className="glass-card p-6 border-l-4 border-white/30">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-10 h-10 rounded-full bg-white/10 border-2 border-white/30 flex items-center justify-center text-xl">
                        🎼
                      </div>
                      <div>
                        <div className="font-bold text-white">The Conductor</div>
                        <div className="text-xs text-gray-500">Final Decision Maker</div>
                      </div>
                    </div>

                    {debate.conductor.probability && (
                      <div className="flex items-center gap-3 mb-4">
                        <div className="text-sm text-gray-400">Combined probability:</div>
                        <span className="font-mono text-xl font-bold text-white">
                          {debate.conductor.favoredTeam} {(debate.conductor.probability * 100).toFixed(0)}%
                        </span>
                        <span className="font-mono text-sm text-gray-500">
                          &#177; {(debate.conductor.uncertainty * 100).toFixed(0)}%
                        </span>
                      </div>
                    )}

                    {debate.conductor.pick && (
                      <div className="bg-cyan-400/10 border border-cyan-400/20 rounded-xl p-4 mb-4 text-center">
                        <div className="text-xs text-cyan-400 uppercase tracking-widest mb-1">Final Pick</div>
                        <div className="font-display text-2xl font-bold text-white">{debate.conductor.pick}</div>
                        <div className="text-sm text-gray-400 mt-1">{debate.conductor.confidence}</div>
                      </div>
                    )}

                    {debate.conductor.quote && (
                      <blockquote className="text-sm text-gray-300 leading-relaxed italic border-l-2 border-gray-600 pl-4 mb-4">
                        "{debate.conductor.quote}"
                      </blockquote>
                    )}

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                      {debate.conductor.keyFactor && (
                        <div className="bg-navy-700/50 rounded-lg p-3">
                          <div className="text-gray-500 uppercase tracking-wider mb-1">Key Factor</div>
                          <div className="text-gray-300">{debate.conductor.keyFactor}</div>
                        </div>
                      )}
                      {debate.conductor.mostWeighted && (
                        <div className="bg-navy-700/50 rounded-lg p-3">
                          <div className="text-gray-500 uppercase tracking-wider mb-1">Most Weighted</div>
                          <div className="text-gray-300">{getAgent(debate.conductor.mostWeighted).emoji} {debate.conductor.mostWeighted}</div>
                        </div>
                      )}
                      {debate.conductor.dissentReport && (
                        <div className="bg-navy-700/50 rounded-lg p-3">
                          <div className="text-gray-500 uppercase tracking-wider mb-1">Dissent</div>
                          <div className="text-gray-400 line-clamp-3">{debate.conductor.dissentReport}</div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Vote Tally */}
                  {debate.voteTally && (
                    <div className="glass-card p-4">
                      <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Vote Tally</div>
                      {Object.entries(debate.voteTally).map(([team, data]) => {
                        const total = Object.values(debate.voteTally).reduce((s, d) => s + d.count, 0)
                        const pct = (data.count / total) * 100
                        return (
                          <div key={team} className="mb-3 last:mb-0">
                            <div className="flex items-center justify-between text-sm mb-1">
                              <span className="font-semibold text-white">{team}</span>
                              <span className="font-mono text-gray-400">{data.count} vote{data.count !== 1 ? 's' : ''}</span>
                            </div>
                            <div className="h-6 bg-navy-700 rounded-lg overflow-hidden flex items-center">
                              <div
                                className="h-full rounded-lg flex items-center px-2 transition-all duration-500"
                                style={{
                                  width: `${pct}%`,
                                  background: team === teamA
                                    ? 'linear-gradient(90deg, #4FC3F7, #29B6F6)'
                                    : 'linear-gradient(90deg, #FF8A65, #FF7043)',
                                }}
                              >
                                <span className="text-[10px] font-bold text-white/90 whitespace-nowrap">
                                  {data.agents.map(a => getAgent(a).emoji).join(' ')}
                                </span>
                              </div>
                            </div>
                            <div className="text-[10px] text-gray-500 mt-0.5">
                              {data.agents.join(', ')}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function AgentCard({ agent, teamA, teamB, isRound2 }) {
  const agentInfo = getAgent(agent.name)
  const probPct = agent.probability != null ? (agent.probability * 100).toFixed(0) : null

  // Determine which team this agent favors
  const favorsHigherSeed = agent.favoredTeam && probPct
  const displayProb = probPct != null ? `${agent.favoredTeam} ${probPct}%` : null

  return (
    <div className={`glass-card p-4 border-l-4 transition-all`} style={{ borderLeftColor: agentInfo.color + '80' }}>
      {/* Agent header */}
      <div className="flex items-center gap-3 mb-2">
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-lg shrink-0"
          style={{ background: agentInfo.color + '18', border: `2px solid ${agentInfo.color}40` }}
        >
          {agentInfo.emoji}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-sm" style={{ color: agentInfo.color }}>{agent.name}</span>
            {agent.model !== 'claude' && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-navy-700 text-gray-500 font-mono">{agent.model}</span>
            )}
          </div>
          <div className="text-[10px] text-gray-500">{agentInfo.role}</div>
        </div>
        {isRound2 && agent.positionChange && (
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
            agent.positionChange === 'STRENGTHENED' ? 'bg-emerald-400/10 text-emerald-400' :
            agent.positionChange === 'WEAKENED' ? 'bg-amber-400/10 text-amber-400' :
            agent.positionChange === 'FLIPPED' ? 'bg-red-400/10 text-red-400' :
            'bg-gray-400/10 text-gray-400'
          }`}>
            {agent.positionChange === 'STRENGTHENED' ? '↑ Strengthened' :
             agent.positionChange === 'WEAKENED' ? '↓ Weakened' :
             agent.positionChange === 'FLIPPED' ? '↻ Flipped' :
             '— Unchanged'}
          </span>
        )}
      </div>

      {/* Cross-examination context */}
      {isRound2 && (agent.disagreesWith || agent.agreesWith) && (
        <div className="mb-2 space-y-1">
          {agent.disagreesWith && (
            <div className="text-xs text-gray-500">
              <span className="text-red-400/70 font-medium">Disagrees:</span>{' '}
              <span className="text-gray-400">{agent.disagreesWith}</span>
            </div>
          )}
          {agent.agreesWith && (
            <div className="text-xs text-gray-500">
              <span className="text-emerald-400/70 font-medium">Agrees:</span>{' '}
              <span className="text-gray-400">{agent.agreesWith}</span>
            </div>
          )}
        </div>
      )}

      {/* Quote */}
      {agent.quote && (
        <blockquote className="text-sm text-gray-300 leading-relaxed mb-2">
          "{agent.quote}"
        </blockquote>
      )}

      {/* Stats row */}
      <div className="flex items-center gap-4 flex-wrap">
        {displayProb && (
          <div className="flex items-center gap-2">
            <div className="w-24 h-1.5 bg-navy-700 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.abs(agent.probability * 100)}%`,
                  background: agentInfo.color,
                  opacity: 0.7,
                }}
              />
            </div>
            <span className="font-mono text-xs text-gray-400">{displayProb}</span>
            {agent.uncertainty && (
              <span className="font-mono text-[10px] text-gray-600">&#177;{(agent.uncertainty * 100).toFixed(0)}%</span>
            )}
          </div>
        )}
        {agent.keyStat && (
          <div className="text-[11px] text-gray-500 italic">{agent.keyStat}</div>
        )}
      </div>
    </div>
  )
}

/* ==================== AGENT PROFILES ==================== */

function AgentProfiles() {
  const agentPerf = gamesData.agent_performance || []

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {AGENTS.map(agent => {
        const perf = agentPerf.find(p =>
          p.agent.toLowerCase() === agent.name.replace('The ', '').toLowerCase() ||
          p.agent.toLowerCase() === agent.name.toLowerCase()
        )
        return (
          <div key={agent.name} className="glass-card p-5 hover:border-cyan-400/30 transition-all group">
            <div className="flex items-center gap-3 mb-3">
              <div
                className="w-12 h-12 rounded-full flex items-center justify-center text-2xl"
                style={{ background: agent.color + '18', border: `2px solid ${agent.color}40` }}
              >
                {agent.emoji}
              </div>
              <div>
                <div className="font-bold text-white text-sm">{agent.name}</div>
                <div className="text-[10px] text-gray-500">{agent.role}</div>
              </div>
            </div>
            <p className="text-xs text-gray-400 leading-relaxed mb-3">{agent.personality}</p>
            <div className="space-y-1.5 text-[11px]">
              <div className="flex justify-between">
                <span className="text-gray-500">Model</span>
                <span className="font-mono text-gray-300">{agent.model}</span>
              </div>
              {perf && (
                <>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Position changes</span>
                    <span className="font-mono text-gray-300">{perf.position_changes}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Avg response</span>
                    <span className="font-mono text-gray-300">{(perf.avg_response_ms / 1000).toFixed(1)}s</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Cost</span>
                    <span className="font-mono text-gray-300">${perf.cost.toFixed(2)}</span>
                  </div>
                </>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ==================== CINDERELLA TRACKER ==================== */

function CinderellaTracker({ onSelectGame }) {
  const cinderellas = [
    {
      team: 'Vanderbilt', seed: 5, emoji: '⚓',
      label: 'To the Championship Game',
      color: '#FFD54F',
      path: [
        { opponent: '#12 McNeese', round: 'R64', vote: '4-3', note: 'Conductor override', result: 'W' },
        { opponent: '#4 Nebraska', round: 'R32', vote: '4-3', note: 'Upset (50.4)', result: 'W' },
        { opponent: '#1 Florida', round: 'S16', vote: '5-2', note: 'Upset (55.1) — beat #1 seed', result: 'W' },
        { opponent: '#2 Houston', round: 'E8', vote: '6-1', note: 'Upset (48.1)', result: 'W' },
        { opponent: '#1 Michigan', round: 'F4', vote: '6-1', note: 'Upset (47.1)', result: 'W' },
        { opponent: '#1 Arizona', round: 'NCG', vote: '4-3', note: 'Championship game', result: 'L' },
      ]
    },
    {
      team: 'USF', seed: 11, emoji: '🐂',
      label: 'To the Elite 8',
      color: '#81C784',
      path: [
        { opponent: '#6 Louisville', round: 'R64', vote: '7-0', note: 'Upset (57.4)', result: 'W' },
        { opponent: '#3 Michigan State', round: 'R32', vote: '4-3', note: 'Cinderella continues', result: 'W' },
        { opponent: '#7 UCLA', round: 'S16', vote: '5-2', note: 'Upset (50.4) — 11-seed in E8', result: 'W' },
        { opponent: '#1 Duke', round: 'E8', vote: '4-3', note: 'Conductor override', result: 'L' },
      ]
    },
    {
      team: 'VCU', seed: 11, emoji: '🐏',
      label: 'To the Sweet 16',
      color: '#CE93D8',
      path: [
        { opponent: '#6 UNC', round: 'R64', vote: '7-0', note: 'Upset (64.4)', result: 'W' },
        { opponent: '#3 Illinois', round: 'R32', vote: '4-3', note: 'Upset (43.4)', result: 'W' },
        { opponent: '#2 Houston', round: 'S16', vote: '4-3', note: 'Conductor override', result: 'L' },
      ]
    },
    {
      team: 'Akron', seed: 12, emoji: '⚡',
      label: 'To the Sweet 16',
      color: '#4FC3F7',
      path: [
        { opponent: '#5 Texas Tech', round: 'R64', vote: '6-1', note: 'Upset (51.2)', result: 'W' },
        { opponent: '#4 Alabama', round: 'R32', vote: '4-3', note: '12-seed continues', result: 'W' },
        { opponent: '#1 Michigan', round: 'S16', vote: '4-3', note: 'Conductor override', result: 'L' },
      ]
    },
    {
      team: 'Texas', seed: 11, emoji: '🤘',
      label: 'To the Sweet 16',
      color: '#FF8A65',
      path: [
        { opponent: '#6 BYU', round: 'R64', vote: '4-3', note: 'Conductor override', result: 'W' },
        { opponent: '#3 Gonzaga', round: 'R32', vote: '4-3', note: 'Cinderella continues', result: 'W' },
        { opponent: '#2 Purdue', round: 'S16', vote: '5-2', note: 'Run ends', result: 'L' },
      ]
    },
  ]

  return (
    <div className="space-y-6">
      {cinderellas.map(c => (
        <div key={c.team} className="glass-card p-5">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">{c.emoji}</span>
            <div>
              <div className="font-display text-xl font-bold text-white">#{c.seed} {c.team}</div>
              <div className="text-xs text-gray-500">{c.label}</div>
            </div>
          </div>
          <div className="space-y-2">
            {c.path.map((step, i) => (
              <div
                key={i}
                className={`flex items-center gap-3 p-2.5 rounded-lg transition-colors ${
                  step.result === 'W' ? 'bg-emerald-400/5 hover:bg-emerald-400/10' : 'bg-red-400/5 hover:bg-red-400/10'
                } cursor-pointer`}
                onClick={() => {
                  const game = gamesData.games.find(g =>
                    g.matchup?.includes(c.team) && g.round === step.round
                  )
                  if (game) onSelectGame(game)
                }}
              >
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                  step.result === 'W'
                    ? 'bg-emerald-400/20 text-emerald-400'
                    : 'bg-red-400/20 text-red-400'
                }`}>
                  {step.result}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-white">vs {step.opponent}</span>
                    <span className="text-[10px] text-gray-500 uppercase">{ROUND_LABELS[step.round]}</span>
                  </div>
                  <div className="text-xs text-gray-500">
                    Vote: {step.vote} &middot; {step.note}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/* ==================== CALIBRATION CHART ==================== */

function CalibrationChart() {
  const data = gamesData.calibration_report?.matchup_results || []

  const maxExpected = 2.5
  const maxActual = 4

  return (
    <div className="glass-card p-6">
      <div className="space-y-3">
        {data.map(row => {
          const expectedPct = parseFloat(row.expected_rate?.replace('~', '').replace('%', '')) || 0
          const expectedCount = row.expected_count
          const actualCount = row.upsets
          const total = row.total

          const isOver = actualCount > expectedCount
          const isUnder = actualCount < expectedCount && expectedCount > 0
          const isOk = row.status === 'OK'

          return (
            <div key={row.matchup} className="flex items-center gap-3">
              <div className="w-12 font-mono text-xs text-gray-400 text-right shrink-0">{row.matchup}</div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  {/* Actual bar */}
                  <div className="flex-1 h-8 bg-navy-700/50 rounded-lg relative overflow-hidden">
                    <div
                      className="absolute inset-y-0 left-0 rounded-lg flex items-center px-2"
                      style={{
                        width: `${(actualCount / total) * 100}%`,
                        background: isUnder ? 'rgba(255, 138, 101, 0.3)' : 'rgba(79, 195, 247, 0.3)',
                        minWidth: actualCount > 0 ? '40px' : '0',
                      }}
                    >
                      <span className="font-mono text-xs font-bold text-white">{actualCount}/{total}</span>
                    </div>
                    {/* Expected marker */}
                    <div
                      className="absolute top-0 bottom-0 w-0.5 bg-gray-500"
                      style={{ left: `${expectedPct}%` }}
                    />
                  </div>
                  <div className="w-16 text-right">
                    <span className={`text-xs font-mono font-semibold ${
                      isOk ? 'text-emerald-400' : 'text-amber-400'
                    }`}>
                      {row.status}
                    </span>
                  </div>
                </div>
                <div className="flex justify-between text-[10px] text-gray-600 mt-0.5">
                  <span>Expected: {row.expected_rate}</span>
                  <span>Actual: {actualCount} upset{actualCount !== 1 ? 's' : ''}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-6 pt-4 border-t border-navy-600/30 flex items-center justify-between">
        <div className="text-sm text-gray-400">
          <span className="font-bold text-white">8 total upsets</span> in 32 R64 games
        </div>
        <div className="text-sm text-gray-500">
          Historical expected range: <span className="font-mono text-gray-300">7-10</span>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-3 text-[10px] text-gray-500">
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded bg-cyan-400/30" /> Actual upsets
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-0.5 bg-gray-500" /> Expected rate
        </div>
      </div>
    </div>
  )
}

/* ==================== HOW IT WORKS ==================== */

function HowItWorks() {
  return (
    <div className="space-y-8">
      {/* Architecture diagram */}
      <div className="glass-card p-6">
        <h3 className="font-display text-xl font-bold text-white mb-4">Debate Architecture</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-navy-700/50 rounded-xl p-5 text-center">
            <div className="text-3xl mb-2">1️⃣</div>
            <div className="font-bold text-white text-sm mb-1">Round 1 — Independent Analysis</div>
            <p className="text-xs text-gray-400">
              Each agent independently analyzes the matchup through their specialty lens.
              Win probabilities, key stats, and reasoning are generated without seeing other agents' work.
            </p>
          </div>
          <div className="bg-navy-700/50 rounded-xl p-5 text-center">
            <div className="text-3xl mb-2">2️⃣</div>
            <div className="font-bold text-white text-sm mb-1">Round 2 — Cross-Examination</div>
            <p className="text-xs text-gray-400">
              Agents see all Round 1 analyses and directly challenge each other.
              They can strengthen, weaken, or flip their positions based on cross-examination.
            </p>
          </div>
          <div className="bg-navy-700/50 rounded-xl p-5 text-center">
            <div className="text-3xl mb-2">🎼</div>
            <div className="font-bold text-white text-sm mb-1">The Conductor's Verdict</div>
            <p className="text-xs text-gray-400">
              Weighted probability math synthesizes all arguments. The Conductor can override
              the majority vote when the numbers tell a different story.
            </p>
          </div>
        </div>
      </div>

      {/* Six Pillars */}
      <div className="glass-card p-6">
        <h3 className="font-display text-xl font-bold text-white mb-4">The Six Pillars</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {[
            { icon: '🏟️', name: 'Tempo & Pace', desc: 'How game speed creates advantages or neutralizes talent gaps' },
            { icon: '🛡️', name: 'Defensive Efficiency', desc: 'Opponent FG%, defensive rating, and defensive consistency' },
            { icon: '💥', name: 'Three-Point Variance', desc: 'How shooting variance creates upset potential on any given night' },
            { icon: '🐺', name: 'Experience & Coaching', desc: 'Senior leadership, coaching pedigree, travel fatigue' },
            { icon: '🔍', name: 'Hidden Edges', desc: 'Injuries, rest advantages, travel distance, chemistry issues' },
            { icon: '📊', name: 'Historical Patterns', desc: 'Base rates, seed matchup history, upset archetypes since 1985' },
          ].map((pillar, i) => (
            <div key={i} className="flex gap-3 p-3 rounded-lg bg-navy-700/30">
              <span className="text-xl shrink-0">{pillar.icon}</span>
              <div>
                <div className="text-sm font-semibold text-white">{pillar.name}</div>
                <div className="text-xs text-gray-500">{pillar.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Tech stack */}
      <div className="glass-card p-6">
        <h3 className="font-display text-xl font-bold text-white mb-4">Technical Details</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
          {[
            { label: 'Claude Agents', value: '3', sub: 'Sonnet 4' },
            { label: 'Gemini Agents', value: '4', sub: '2.5 Flash' },
            { label: 'Total Tokens', value: '2.8M', sub: 'in + out' },
            { label: 'Run Time', value: '23 min', sub: '22s/game avg' },
          ].map((s, i) => (
            <div key={i}>
              <div className="font-mono text-2xl font-bold text-white">{s.value}</div>
              <div className="text-xs text-gray-400">{s.label}</div>
              <div className="text-[10px] text-gray-600">{s.sub}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
