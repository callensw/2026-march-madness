import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase, tables } from '../lib/supabase';

const REGIONS = ['East', 'West', 'South', 'Midwest'];
const SEED_ORDER = [1, 16, 8, 9, 5, 12, 4, 13, 6, 11, 3, 14, 7, 10, 2, 15];

const s = {
  page: { padding: '32px 40px' },
  title: { fontSize: 28, fontWeight: 700, color: '#fff', margin: 0 },
  subtitle: { fontSize: 14, color: '#666', marginTop: 4, marginBottom: 24 },
  regionTabs: { display: 'flex', gap: 8, marginBottom: 24 },
  tab: (active) => ({
    padding: '8px 20px',
    borderRadius: 8,
    border: '1px solid ' + (active ? '#4A90D9' : '#1e1e1e'),
    background: active ? 'rgba(74,144,217,0.15)' : '#141414',
    color: active ? '#4A90D9' : '#888',
    cursor: 'pointer',
    fontSize: 14,
    fontWeight: active ? 600 : 400,
  }),
  bracketWrap: {
    overflowX: 'auto',
    padding: '0 0 24px',
  },
  loading: { padding: '80px 40px', textAlign: 'center', color: '#555', fontSize: 16 },
};

const GAME_W = 200;
const GAME_H = 48;
const ROUND_GAP = 60;
const GAME_VGAP = 12;

export default function BracketView() {
  const navigate = useNavigate();
  const [games, setGames] = useState([]);
  const [teams, setTeams] = useState({});
  const [loading, setLoading] = useState(true);
  const [region, setRegion] = useState('East');

  useEffect(() => {
    async function fetchData() {
      const [gamesRes, teamsRes] = await Promise.all([
        supabase.from(tables.games).select('*'),
        supabase.from(tables.teams).select('*'),
      ]);
      if (gamesRes.data) setGames(gamesRes.data);
      if (teamsRes.data) {
        const map = {};
        teamsRes.data.forEach((t) => { map[t.id] = t; });
        setTeams(map);
      }
      setLoading(false);
    }
    fetchData();
  }, []);

  if (loading) return <div style={s.loading}>Loading bracket data...</div>;

  // Group games by region (via team region)
  const regionGames = games.filter((g) => {
    const tA = teams[g.team_a_id];
    const tB = teams[g.team_b_id];
    return (tA && tA.region === region) || (tB && tB.region === region);
  });

  // Organize by round
  const rounds = {};
  regionGames.forEach((g) => {
    const r = g.round || 1;
    if (!rounds[r]) rounds[r] = [];
    rounds[r].push(g);
  });

  const roundNumbers = Object.keys(rounds).map(Number).sort((a, b) => a - b);
  if (roundNumbers.length === 0) roundNumbers.push(1);

  // Sort first round by seed matchup order
  if (rounds[1]) {
    rounds[1].sort((a, b) => {
      const aMin = Math.min(teams[a.team_a_id]?.seed || 99, teams[a.team_b_id]?.seed || 99);
      const bMin = Math.min(teams[b.team_a_id]?.seed || 99, teams[b.team_b_id]?.seed || 99);
      return SEED_ORDER.indexOf(aMin) - SEED_ORDER.indexOf(bMin);
    });
  }

  // Compute dimensions
  const firstRoundCount = rounds[roundNumbers[0]]?.length || 8;
  const totalRounds = roundNumbers.length || 4;
  const svgW = totalRounds * (GAME_W + ROUND_GAP) + 40;
  const svgH = firstRoundCount * (GAME_H + GAME_VGAP) + 40;

  return (
    <div style={s.page}>
      <h1 style={s.title}>Bracket</h1>
      <p style={s.subtitle}>64-team tournament bracket visualization</p>

      <div style={s.regionTabs}>
        {REGIONS.map((r) => (
          <div key={r} style={s.tab(r === region)} onClick={() => setRegion(r)}>
            {r}
          </div>
        ))}
      </div>

      {games.length === 0 ? (
        <div style={{ background: '#141414', border: '1px solid #1e1e1e', borderRadius: 12, padding: 60, textAlign: 'center', color: '#555' }}>
          Waiting for bracket data...
        </div>
      ) : (
        <div style={s.bracketWrap}>
          <svg width={svgW} height={svgH} style={{ display: 'block' }}>
            {roundNumbers.map((roundNum, ri) => {
              const roundGames = rounds[roundNum] || [];
              const gamesInRound = roundGames.length || Math.max(1, firstRoundCount / Math.pow(2, ri));
              const spacing = svgH / gamesInRound;
              const x = 20 + ri * (GAME_W + ROUND_GAP);

              return roundGames.map((game, gi) => {
                const y = spacing * gi + spacing / 2 - GAME_H / 2;
                const teamA = teams[game.team_a_id];
                const teamB = teams[game.team_b_id];
                const analyzed = !!game.conductor_pick;
                const borderColor = analyzed ? '#2d6a30' : '#1e1e1e';
                const bgColor = analyzed ? '#0f1f10' : '#141414';

                // Connector lines to next round
                const nextX = x + GAME_W;
                const midY = y + GAME_H / 2;

                return (
                  <g key={game.id}>
                    {/* Connector line */}
                    {ri < roundNumbers.length - 1 && (
                      <line
                        x1={nextX}
                        y1={midY}
                        x2={nextX + ROUND_GAP * 0.4}
                        y2={midY}
                        stroke="#1e1e1e"
                        strokeWidth={1}
                      />
                    )}

                    {/* Game box */}
                    <rect
                      x={x}
                      y={y}
                      width={GAME_W}
                      height={GAME_H}
                      rx={6}
                      fill={bgColor}
                      stroke={borderColor}
                      strokeWidth={1}
                      style={{ cursor: 'pointer' }}
                      onClick={() => navigate(`/debate/${game.id}`)}
                    />

                    {/* Team A */}
                    <text
                      x={x + 8}
                      y={y + 18}
                      fill="#e0e0e0"
                      fontSize={12}
                      fontFamily="system-ui, sans-serif"
                    >
                      <tspan fill="#666" fontSize={10}>{teamA?.seed || '?'} </tspan>
                      {teamA?.name || 'TBD'}
                    </text>

                    {/* Divider */}
                    <line
                      x1={x + 4}
                      y1={y + GAME_H / 2}
                      x2={x + GAME_W - 4}
                      y2={y + GAME_H / 2}
                      stroke="#1e1e1e"
                      strokeWidth={0.5}
                    />

                    {/* Team B */}
                    <text
                      x={x + 8}
                      y={y + 38}
                      fill="#e0e0e0"
                      fontSize={12}
                      fontFamily="system-ui, sans-serif"
                    >
                      <tspan fill="#666" fontSize={10}>{teamB?.seed || '?'} </tspan>
                      {teamB?.name || 'TBD'}
                    </text>

                    {/* Score if available */}
                    {game.score_a != null && (
                      <text x={x + GAME_W - 8} y={y + 18} fill="#888" fontSize={12} textAnchor="end" fontFamily="system-ui, sans-serif">
                        {game.score_a}
                      </text>
                    )}
                    {game.score_b != null && (
                      <text x={x + GAME_W - 8} y={y + 38} fill="#888" fontSize={12} textAnchor="end" fontFamily="system-ui, sans-serif">
                        {game.score_b}
                      </text>
                    )}

                    {/* Analyzed indicator */}
                    {analyzed && (
                      <circle
                        cx={x + GAME_W - 12}
                        cy={y + GAME_H / 2}
                        r={3}
                        fill="#4ade80"
                      />
                    )}
                  </g>
                );
              });
            })}
          </svg>
        </div>
      )}
    </div>
  );
}
