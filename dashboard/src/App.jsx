import { useState, useMemo } from 'react'
import './App.css'
import gamesData from './data/games.json'
import debatesData from './data/debates.json'
import { getAgent } from './lib/agents'

// ═══════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════

const ROUND_LABELS = {
  R64: 'Round of 64', R32: 'Round of 32', S16: 'Sweet 16',
  E8: 'Elite 8', F4: 'Final Four', NCG: 'Championship'
}

const ROUND_ORDER = ['R64', 'R32', 'S16', 'E8']
const ROUND_ORDER_REVERSED = ['E8', 'S16', 'R32', 'R64']

const AGENT_MOVES = {
  'TEMPO HAWK': 'PACE ANALYSIS',
  'IRON CURTAIN': 'DEFENSIVE WALL',
  'GLASS CANNON': 'SHOOTING BARRAGE',
  'ROAD DOG': 'VETERAN WISDOM',
  'WHISPER': 'HIDDEN INTEL',
  'ORACLE': 'HISTORICAL PROPHECY',
  'STREAK': 'MOMENTUM SURGE',
  'THE CONDUCTOR': 'FINAL VERDICT',
}

const BIOME_CONFIG = {
  East:    { name: 'Frozen Tundra',       icon: '❄️',  accent: '#4FC3F7', terrain: ['🏔️','❄️','⛰️','🌨️','❄️','🏔️'] },
  West:    { name: 'Desert Wastes',       icon: '🏜️',  accent: '#FFB74D', terrain: ['🌵','🏜️','☀️','🌵','🦎','🌵'] },
  Midwest: { name: 'Dark Forest',         icon: '🌲',  accent: '#81C784', terrain: ['🌲','🍄','🌿','🌲','🦌','🌲'] },
  South:   { name: 'Volcanic Highlands',  icon: '🌋',  accent: '#EF5350', terrain: ['🌋','🔥','🪨','🌋','⚡','🔥'] },
}

const CINDERELLA_TITLES = {
  'Vanderbilt': "The Commodore's Quest",
  'USF': 'The Bull Run',
  'VCU': "The Ram's Charge",
  'Akron': 'The Zip Line',
  'Texas': 'The Longhorn Trail',
}

// ═══════════════════════════════════════════════════════
// Utility Functions
// ═══════════════════════════════════════════════════════

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

function parseVoteSplit(vs) {
  const m = (vs || '').match(/(\d+)-(\d+)/)
  if (!m) return { majority: 0, minority: 0 }
  return { majority: +m[1], minority: +m[2] }
}

function getNodeType(game) {
  if (isUpset(game)) return 'upset'
  const { majority, minority } = parseVoteSplit(game.vote_split)
  if (majority === 7 && minority === 0) return 'blowout'
  if (majority === 4 && minority === 3) return 'close'
  return 'chalk'
}

// ═══════════════════════════════════════════════════════
// Precomputed Data
// ═══════════════════════════════════════════════════════

const games = gamesData.games

const teamPaths = {}
games.forEach(g => {
  const wInfo = getWinnerInfo(g)
  const lInfo = getLoserInfo(g)
  if (!teamPaths[g.winner]) teamPaths[g.winner] = { seed: wInfo.seed, wins: [], eliminated: null }
  teamPaths[g.winner].wins.push(g)
  if (lInfo.team) {
    if (!teamPaths[lInfo.team]) teamPaths[lInfo.team] = { seed: lInfo.seed, wins: [], eliminated: null }
    teamPaths[lInfo.team].eliminated = g
  }
})

const cinderellas = Object.entries(teamPaths)
  .filter(([, data]) => data.seed >= 5 && data.wins.length >= 2)
  .sort((a, b) => b[1].wins.length - a[1].wins.length)

// ═══════════════════════════════════════════════════════
// Components
// ═══════════════════════════════════════════════════════

// ── Title Screen ─────────────────────────────────────

function TitleScreen({ onStart }) {
  return (
    <div className="title-screen" onClick={onStart}>
      <div className="title-stars" />
      <div className="title-frame title-corners-bottom">
        <div className="title-main">MARCH MADNESS</div>
        <div className="title-sub">AI WAR ROOM</div>
        <div className="title-edition">~ 16-Bit Edition ~</div>
        <div className="title-stats">
          8 AI Analysts<br/>
          63 Games Debated<br/>
          Every Pick Recorded
        </div>
        <div className="title-champion">🏆 Champion: (1) Arizona</div>
        <button className="title-start">▶ PRESS START</button>
      </div>
    </div>
  )
}

// ── Game Node ────────────────────────────────────────

function GameNode({ game, onClick, cinderellaTeam }) {
  const winner = getWinnerInfo(game)
  const loser = getLoserInfo(game)
  const nodeType = getNodeType(game)
  const roundClass = game.round.toLowerCase()

  const isPartOfJourney = cinderellaTeam && (
    winner.team === cinderellaTeam || loser.team === cinderellaTeam
  )

  return (
    <div
      className={`game-node ${roundClass} ${nodeType} ${isPartOfJourney ? 'highlighted' : ''}`}
      onClick={(e) => { e.stopPropagation(); onClick(game) }}
    >
      <span>{winner.seed}</span>
      <div className="node-tooltip">
        {game.matchup}<br/>
        Pick: {game.winner} ({game.vote_split})
      </div>
    </div>
  )
}

// ── Biome Panel ──────────────────────────────────────

function BiomePanel({ region, regionGames, onSelectGame, cinderellaTeam, reversed }) {
  const biome = BIOME_CONFIG[region]
  const order = reversed ? ROUND_ORDER_REVERSED : ROUND_ORDER

  const gamesByRound = {}
  regionGames.forEach(g => {
    if (!gamesByRound[g.round]) gamesByRound[g.round] = []
    gamesByRound[g.round].push(g)
  })

  // Decorative terrain positions
  const terrainPositions = [
    { top: '10%', left: '85%' },
    { top: '30%', right: '5%' },
    { top: '55%', left: '90%' },
    { top: '75%', right: '10%' },
    { top: '45%', left: '5%' },
    { top: '85%', left: '80%' },
  ]

  return (
    <div className={`biome-panel ${region.toLowerCase()}`}>
      {biome.terrain.map((t, i) => (
        <span key={i} className="biome-terrain" style={terrainPositions[i]}>{t}</span>
      ))}
      <div className="biome-label" style={{ color: biome.accent }}>
        {biome.icon} {region.toUpperCase()}
      </div>
      <div className="biome-sublabel">{biome.name}</div>
      {order.map(round => {
        const roundGames = gamesByRound[round]
        if (!roundGames || !roundGames.length) return null
        return (
          <div key={round} className="round-group">
            <div className="round-label">{ROUND_LABELS[round]}</div>
            <div className="round-nodes">
              {roundGames.map(g => (
                <GameNode
                  key={g.game_number}
                  game={g}
                  onClick={onSelectGame}
                  cinderellaTeam={cinderellaTeam}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Castle Section ───────────────────────────────────

function CastleSection({ f4Games, ncgGame, onSelectGame, cinderellaTeam }) {
  const champion = ncgGame ? getWinnerInfo(ncgGame) : null

  return (
    <div className="castle-section">
      {/* Castle pixel art */}
      <div className="castle-visual">
        <div className="castle-towers">
          <div className="tower">
            <div className="tower-cap" />
            <div className="tower-body small" />
          </div>
          <div className="tower">
            <div className="tower-cap gold" />
            <div className="tower-body tall" />
          </div>
          <div className="tower">
            <div className="tower-cap" />
            <div className="tower-body small" />
          </div>
        </div>
        <div className="castle-wall">
          <span className="castle-gate">🏆</span>
          <span className="castle-banner-text">WAR ROOM</span>
        </div>
      </div>

      <div className="castle-label">THE CASTLE</div>

      {/* Championship */}
      {ncgGame && (
        <div className="castle-games">
          <div className="castle-round-label">CHAMPIONSHIP</div>
          <div className="castle-nodes">
            <GameNode game={ncgGame} onClick={onSelectGame} cinderellaTeam={cinderellaTeam} />
          </div>
        </div>
      )}

      {/* Final Four */}
      {f4Games.length > 0 && (
        <div className="castle-games">
          <div className="castle-round-label">FINAL FOUR</div>
          <div className="castle-nodes">
            {f4Games.map(g => (
              <GameNode key={g.game_number} game={g} onClick={onSelectGame} cinderellaTeam={cinderellaTeam} />
            ))}
          </div>
        </div>
      )}

      {/* Champion display */}
      {champion && (
        <div className="champion-display">
          <div className="champion-name">👑 #{champion.seed} {champion.team}</div>
        </div>
      )}
    </div>
  )
}

// ── Cinderella Bar ───────────────────────────────────

function CinderellaBar({ selected, onSelect }) {
  if (!cinderellas.length) return null
  return (
    <div className="cinderella-bar">
      <span className="cinderella-label">⚓ QUEST LINES:</span>
      {cinderellas.map(([team, data]) => (
        <button
          key={team}
          className={`cinderella-btn ${selected === team ? 'active' : ''}`}
          onClick={() => onSelect(team)}
        >
          #{data.seed} {team} ({data.wins.length}W)
        </button>
      ))}
    </div>
  )
}

// ── Cinderella Info ──────────────────────────────────

function CinderellaInfo({ team }) {
  const path = teamPaths[team]
  if (!path) return null

  const title = CINDERELLA_TITLES[team] || 'The Journey'
  const steps = path.wins.map(g => {
    const loser = getLoserInfo(g)
    return `Beat #${loser.seed} ${loser.team} (${ROUND_LABELS[g.round]})`
  })
  const ending = path.eliminated
    ? `Fell to ${getWinnerInfo(path.eliminated).team} in ${ROUND_LABELS[path.eliminated.round]}`
    : 'CHAMPION'

  return (
    <div className="cinderella-info">
      <div className="cinderella-title">⚓ {team.toUpperCase()} — {title}</div>
      <div className="cinderella-step">
        {steps.map((s, i) => (
          <span key={i}>
            <span>{s}</span>
            {i < steps.length - 1 ? ' → ' : ''}
          </span>
        ))}
        <br/>
        {ending}
      </div>
    </div>
  )
}

// ── Battle Entry ─────────────────────────────────────

function BattleEntry({ entry, round }) {
  const agent = getAgent(entry.name)
  const moveName = AGENT_MOVES[entry.name?.toUpperCase()] || 'ANALYSIS'
  const prob = entry.probability || 0
  const favored = entry.favoredTeam || '???'

  const statusLabels = {
    STRENGTHENED: '⬆ POWER UP!',
    WEAKENED: '⬇ DEFENSE DOWN!',
    FLIPPED: '💥 CRITICAL HIT!',
    UNCHANGED: '— HELD FIRM',
  }

  const pc = (entry.positionChange || '').toUpperCase()

  return (
    <div className="battle-entry">
      {round === 2 && pc && statusLabels[pc] && (
        <div className={`entry-status ${pc.toLowerCase()}`}>
          {statusLabels[pc]}
        </div>
      )}

      <div className="entry-header">
        <span style={{ color: agent.color }}>{agent.emoji} {entry.name}</span>
        {' '}used{' '}
        <span style={{ color: agent.color }}>{moveName}!</span>
      </div>

      <div className="entry-quote" style={{ borderColor: agent.color }}>
        &ldquo;{entry.quote}&rdquo;
      </div>

      <div className="entry-stats">
        <span className="entry-pick-label">Pick: {favored} ({Math.round(prob * 100)}%)</span>
        <div className="prob-bar">
          <div
            className="prob-fill"
            style={{ width: `${prob * 100}%`, background: agent.color }}
          />
        </div>
      </div>

      {entry.keyStat && (
        <div className="entry-key-stat">★ {entry.keyStat}</div>
      )}

      {round === 2 && entry.disagreesWith && (
        <div className="entry-key-stat" style={{ color: '#EF5350' }}>
          ⚔ {entry.disagreesWith}
        </div>
      )}
    </div>
  )
}

// ── Verdict Section ──────────────────────────────────

function VerdictSection({ conductor, voteTally }) {
  return (
    <div className="verdict-section">
      <div className="verdict-header">🎼 THE CONDUCTOR SPEAKS...</div>

      <div className="verdict-quote">
        &ldquo;{conductor.quote}&rdquo;
      </div>

      {voteTally && (
        <div className="verdict-vote">
          FINAL VOTE:{' '}
          {Object.entries(voteTally).map(([team, data], i) => (
            <span key={team}>
              {i > 0 ? ' — ' : ''}
              {team} {data.count}
            </span>
          ))}
        </div>
      )}

      {conductor.pick && (
        <div className="verdict-pick">
          PICK: {conductor.pick}
          {conductor.confidence ? ` (${conductor.confidence})` : ''}
        </div>
      )}

      {conductor.keyFactor && (
        <div className="verdict-factor">
          Key factor: {conductor.keyFactor}
        </div>
      )}

      {conductor.dissentReport && (
        <div className="verdict-factor" style={{ marginTop: '8px' }}>
          Dissent: {conductor.dissentReport}
        </div>
      )}
    </div>
  )
}

// ── Battle Screen ────────────────────────────────────

function BattleScreen({ game, onBack }) {
  const debate = findDebate(game)
  const p = parseMatchup(game.matchup)
  const winner = getWinnerInfo(game)

  const spriteColorA = p && game.winner === p.teamA ? '#4FC3F7' : '#444'
  const spriteColorB = p && game.winner === p.teamB ? '#4FC3F7' : '#444'
  const classA = p && game.winner === p.teamA ? 'winner' : 'loser'
  const classB = p && game.winner === p.teamB ? 'winner' : 'loser'

  return (
    <div className="battle-screen">
      {/* Teams facing off */}
      <div className="battle-header">
        <div className="battle-team">
          <div
            className={`battle-sprite ${classA}`}
            style={{ borderColor: spriteColorA, color: spriteColorA }}
          >
            {p?.seedA}
          </div>
          <div className="battle-team-name">{p?.teamA}</div>
          <div className="battle-team-seed">#{p?.seedA} seed</div>
        </div>

        <div className="battle-vs">VS</div>

        <div className="battle-team">
          <div
            className={`battle-sprite ${classB}`}
            style={{ borderColor: spriteColorB, color: spriteColorB }}
          >
            {p?.seedB}
          </div>
          <div className="battle-team-name">{p?.teamB}</div>
          <div className="battle-team-seed">#{p?.seedB} seed</div>
        </div>
      </div>

      <div className="battle-round-info">
        {game.region} — {ROUND_LABELS[game.round]} — Vote: {game.vote_split}
      </div>

      {debate ? (
        <div className="battle-log">
          {/* Round 1 */}
          <div className="battle-round-divider">
            ━━ ROUND 1 — INDEPENDENT ANALYSIS ━━
          </div>
          {(debate.round1 || []).map((entry, i) => (
            <BattleEntry key={`r1-${i}`} entry={entry} round={1} />
          ))}

          {/* Round 2 */}
          {debate.round2 && debate.round2.length > 0 && (
            <>
              <div className="battle-round-divider">
                ━━ ROUND 2 — CROSS EXAMINATION ━━
              </div>
              {debate.round2.map((entry, i) => (
                <BattleEntry key={`r2-${i}`} entry={entry} round={2} />
              ))}
            </>
          )}

          {/* Conductor Verdict */}
          {debate.conductor && (
            <VerdictSection
              conductor={debate.conductor}
              voteTally={debate.voteTally}
            />
          )}
        </div>
      ) : (
        <div className="battle-log">
          <div className="lost-scroll">
            <span className="lost-scroll-icon">📜</span>
            The scrolls for this battle have been<br/>
            lost to time...<br/><br/>
            Pick: {game.winner} ({game.vote_split})<br/>
            {game.conductor_key_factor && (
              <>Key factor: {game.conductor_key_factor}</>
            )}
          </div>
        </div>
      )}

      {/* Victory */}
      <div className="victory-banner">
        <div className="victory-text">VICTORY!</div>
        <div className="victory-winner">
          #{winner.seed} {winner.team} advances
          {isUpset(game) ? ' — UPSET!' : ''}
        </div>
      </div>

      <button className="back-btn" onClick={onBack}>
        ◀ RETURN TO MAP
      </button>
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// App
// ═══════════════════════════════════════════════════════

export default function App() {
  const [screen, setScreen] = useState('title')
  const [selectedGame, setSelectedGame] = useState(null)
  const [cinderellaTeam, setCinderellaTeam] = useState(null)

  const regionGames = useMemo(() => {
    const result = { East: [], West: [], Midwest: [], South: [] }
    games.forEach(g => {
      if (g.round !== 'F4' && g.round !== 'NCG' && result[g.region]) {
        result[g.region].push(g)
      }
    })
    return result
  }, [])

  const f4Games = useMemo(() => games.filter(g => g.round === 'F4'), [])
  const ncgGame = useMemo(() => games.find(g => g.round === 'NCG'), [])

  const handleSelectGame = (game) => {
    setSelectedGame(game)
    setScreen('battle')
    window.scrollTo(0, 0)
  }

  const handleBack = () => {
    setSelectedGame(null)
    setScreen('map')
  }

  // ── Title Screen ──
  if (screen === 'title') {
    return <TitleScreen onStart={() => setScreen('map')} />
  }

  // ── Battle Screen ──
  if (screen === 'battle' && selectedGame) {
    return <BattleScreen game={selectedGame} onBack={handleBack} />
  }

  // ── Overworld Map ──
  return (
    <div className="overworld">
      <div className="map-header">
        <div className="map-title">MARCH MADNESS AI WAR ROOM</div>
        <div className="map-subtitle">~ 16-Bit Edition ~ Click any orb to enter battle ~</div>
      </div>

      <CinderellaBar
        selected={cinderellaTeam}
        onSelect={(t) => setCinderellaTeam(t === cinderellaTeam ? null : t)}
      />

      {cinderellaTeam && <CinderellaInfo team={cinderellaTeam} />}

      <div className="biome-grid">
        <BiomePanel
          region="East"
          regionGames={regionGames.East}
          onSelectGame={handleSelectGame}
          cinderellaTeam={cinderellaTeam}
        />

        <CastleSection
          f4Games={f4Games}
          ncgGame={ncgGame}
          onSelectGame={handleSelectGame}
          cinderellaTeam={cinderellaTeam}
        />

        <BiomePanel
          region="West"
          regionGames={regionGames.West}
          onSelectGame={handleSelectGame}
          cinderellaTeam={cinderellaTeam}
        />

        <BiomePanel
          region="Midwest"
          regionGames={regionGames.Midwest}
          onSelectGame={handleSelectGame}
          cinderellaTeam={cinderellaTeam}
          reversed
        />

        <BiomePanel
          region="South"
          regionGames={regionGames.South}
          onSelectGame={handleSelectGame}
          cinderellaTeam={cinderellaTeam}
          reversed
        />
      </div>

      <div className="map-legend">
        <div className="legend-item">
          <div className="legend-dot chalk-dot" />
          <span>Chalk</span>
        </div>
        <div className="legend-item">
          <div className="legend-dot upset-dot" />
          <span>Upset</span>
        </div>
        <div className="legend-item">
          <div className="legend-dot close-dot" />
          <span>Close (4-3)</span>
        </div>
        <div className="legend-item">
          <div className="legend-dot blowout-dot" />
          <span>Blowout (7-0)</span>
        </div>
      </div>
    </div>
  )
}
