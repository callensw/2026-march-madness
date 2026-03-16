import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase, tables } from '../lib/supabase';
import { AGENTS, getAgent } from '../lib/agents';

const s = {
  page: { padding: '32px 40px', maxWidth: 1200 },
  header: { marginBottom: 32 },
  title: { fontSize: 28, fontWeight: 700, color: '#fff', margin: 0 },
  subtitle: { fontSize: 14, color: '#666', marginTop: 4 },
  statsBar: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 16,
    marginBottom: 32,
  },
  statCard: {
    background: '#141414',
    border: '1px solid #1e1e1e',
    borderRadius: 12,
    padding: '20px 24px',
  },
  statLabel: { fontSize: 12, color: '#666', textTransform: 'uppercase', letterSpacing: '0.5px' },
  statValue: { fontSize: 32, fontWeight: 700, color: '#fff', marginTop: 4 },
  statSub: { fontSize: 12, color: '#555', marginTop: 2 },
  liveRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 24,
    padding: '10px 16px',
    background: '#141414',
    border: '1px solid #1e1e1e',
    borderRadius: 8,
    fontSize: 13,
  },
  dot: (alive) => ({
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: alive ? '#4ade80' : '#ef4444',
    boxShadow: alive ? '0 0 8px #4ade8088' : 'none',
    animation: alive ? 'pulse 2s infinite' : 'none',
  }),
  sectionTitle: { fontSize: 18, fontWeight: 600, color: '#fff', marginBottom: 16 },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(340, 1fr))',
    gap: 16,
  },
  card: {
    background: '#141414',
    border: '1px solid #1e1e1e',
    borderRadius: 12,
    padding: 20,
    cursor: 'pointer',
    transition: 'border-color 0.15s',
  },
  matchup: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  teamName: { fontSize: 15, fontWeight: 600, color: '#e0e0e0' },
  seed: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 22,
    height: 22,
    borderRadius: '50%',
    background: '#222',
    fontSize: 11,
    fontWeight: 600,
    color: '#aaa',
    marginRight: 8,
  },
  vs: { fontSize: 12, color: '#444', fontWeight: 500 },
  confBar: (pct, color) => ({
    height: 6,
    borderRadius: 3,
    background: '#1e1e1e',
    marginTop: 8,
    position: 'relative',
    overflow: 'hidden',
  }),
  confFill: (pct, color) => ({
    position: 'absolute',
    top: 0,
    left: 0,
    height: '100%',
    width: `${pct}%`,
    borderRadius: 3,
    background: color || '#4A90D9',
  }),
  pickRow: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, fontSize: 13 },
  pickLabel: { color: '#666' },
  pickValue: { color: '#fff', fontWeight: 600 },
  voteSplit: { display: 'flex', height: 4, borderRadius: 2, overflow: 'hidden', marginTop: 8, gap: 1 },
  loading: { padding: '80px 40px', textAlign: 'center', color: '#555', fontSize: 16 },
};

export default function Dashboard() {
  const navigate = useNavigate();
  const [games, setGames] = useState([]);
  const [teams, setTeams] = useState({});
  const [votes, setVotes] = useState([]);
  const [accuracy, setAccuracy] = useState([]);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const [gamesRes, teamsRes, votesRes, accRes] = await Promise.all([
          supabase.from(tables.games).select('*').order('created_at', { ascending: false }).limit(20),
          supabase.from(tables.teams).select('*'),
          supabase.from(tables.agentVotes).select('*'),
          supabase.from(tables.agentAccuracy).select('*'),
        ]);

        const errors = [gamesRes, teamsRes, votesRes, accRes]
          .filter((r) => r.error)
          .map((r) => r.error.message);
        if (errors.length > 0) {
          setError(`Failed to load data: ${errors.join('; ')}`);
        } else {
          setError(null);
        }

        if (gamesRes.data) setGames(gamesRes.data);
        if (teamsRes.data) {
          const map = {};
          teamsRes.data.forEach((t) => { map[t.id] = t; });
          setTeams(map);
        }
        if (votesRes.data) setVotes(votesRes.data);
        if (accRes.data) setAccuracy(accRes.data);
      } catch (err) {
        setError(`Unexpected error: ${err.message}`);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  // Poll status.json with exponential backoff on failures
  useEffect(() => {
    let timeoutId = null;
    let consecutiveFailures = 0;
    const MAX_RETRIES = 5;
    const BASE_INTERVAL = 10000;

    async function poll() {
      try {
        const res = await fetch('/status.json');
        if (res.ok) {
          setStatus(await res.json());
          consecutiveFailures = 0;
        } else {
          consecutiveFailures++;
          setStatus(null);
        }
      } catch {
        consecutiveFailures++;
        setStatus(null);
      }

      if (consecutiveFailures >= MAX_RETRIES) {
        // Stop polling after too many consecutive failures
        return;
      }

      const delay = consecutiveFailures > 0
        ? Math.min(BASE_INTERVAL * Math.pow(2, consecutiveFailures), 300000)
        : BASE_INTERVAL;
      timeoutId = setTimeout(poll, delay);
    }

    poll();
    return () => { if (timeoutId) clearTimeout(timeoutId); };
  }, []);

  if (loading) {
    return <div style={s.loading}>Loading swarm data...</div>;
  }

  if (error) {
    return (
      <div style={{ ...s.loading, color: '#ef4444' }}>
        <div style={{ marginBottom: 8, fontWeight: 600 }}>Error</div>
        <div>{error}</div>
      </div>
    );
  }

  const analyzedGames = games.filter((g) => g.conductor_pick);
  const upsetCount = games.filter((g) => {
    if (!g.conductor_pick) return false;
    const teamA = teams[g.team_a_id];
    const teamB = teams[g.team_b_id];
    if (!teamA || !teamB) return false;
    const pickedTeam = g.conductor_pick === teamA.name ? teamA : teamB;
    const otherTeam = g.conductor_pick === teamA.name ? teamB : teamA;
    return pickedTeam.seed > otherTeam.seed;
  }).length;

  const totalCorrect = accuracy.reduce((s, a) => s + (a.correct_picks || 0), 0);
  const totalPicks = accuracy.reduce((s, a) => s + (a.total_picks || 0), 0);
  const swarmAcc = totalPicks > 0 ? ((totalCorrect / totalPicks) * 100).toFixed(1) : '--';

  const topAgent = accuracy.length > 0
    ? accuracy.reduce((best, a) => {
        const acc = a.total_picks > 0 ? a.correct_picks / a.total_picks : 0;
        const bestAcc = best.total_picks > 0 ? best.correct_picks / best.total_picks : 0;
        return acc > bestAcc ? a : best;
      })
    : null;

  const votesByGame = {};
  votes.forEach((v) => {
    if (!votesByGame[v.game_id]) votesByGame[v.game_id] = [];
    votesByGame[v.game_id].push(v);
  });

  return (
    <div style={s.page}>
      <div style={s.header}>
        <h1 style={s.title}>Dashboard</h1>
        <p style={s.subtitle}>Real-time swarm intelligence for March Madness 2026</p>
      </div>

      <div style={s.statsBar}>
        <div style={s.statCard}>
          <div style={s.statLabel}>Games Analyzed</div>
          <div style={s.statValue}>{analyzedGames.length}</div>
          <div style={s.statSub}>of {games.length} total</div>
        </div>
        <div style={s.statCard}>
          <div style={s.statLabel}>Upsets Called</div>
          <div style={{ ...s.statValue, color: '#FFB347' }}>{upsetCount}</div>
          <div style={s.statSub}>lower seed picked</div>
        </div>
        <div style={s.statCard}>
          <div style={s.statLabel}>Swarm Accuracy</div>
          <div style={{ ...s.statValue, color: '#4ade80' }}>{swarmAcc}%</div>
          <div style={s.statSub}>{totalCorrect}/{totalPicks} correct</div>
        </div>
        <div style={s.statCard}>
          <div style={s.statLabel}>Top Agent</div>
          <div style={{ ...s.statValue, fontSize: 22 }}>
            {topAgent ? `${getAgent(topAgent.agent_name).emoji} ${topAgent.agent_name}` : '--'}
          </div>
          <div style={s.statSub}>
            {topAgent && topAgent.total_picks > 0
              ? `${((topAgent.correct_picks / topAgent.total_picks) * 100).toFixed(1)}% accuracy`
              : ''}
          </div>
        </div>
      </div>

      <div style={s.liveRow}>
        <div style={s.dot(!!status)} />
        <span style={{ color: status ? '#4ade80' : '#ef4444', fontWeight: 600 }}>
          {status ? 'LIVE' : 'OFFLINE'}
        </span>
        <span style={{ color: '#555' }}>
          {status?.message || 'Swarm status unavailable'}
        </span>
        {status?.last_run && (
          <span style={{ marginLeft: 'auto', color: '#444', fontSize: 12 }}>
            Last run: {new Date(status.last_run).toLocaleString()}
          </span>
        )}
      </div>

      <h2 style={s.sectionTitle}>Recent Games</h2>
      {games.length === 0 ? (
        <div style={{ ...s.statCard, textAlign: 'center', color: '#555', padding: 40 }}>
          Waiting for bracket data...
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 16 }}>
          {games.map((game) => {
            const teamA = teams[game.team_a_id];
            const teamB = teams[game.team_b_id];
            const conf = game.conductor_confidence || 0;
            const gVotes = votesByGame[game.id] || [];

            return (
              <div
                key={game.id}
                style={s.card}
                onClick={() => navigate(`/debate/${game.id}`)}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#333'; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#1e1e1e'; }}
              >
                <div style={s.matchup}>
                  <div>
                    <span style={s.seed}>{teamA?.seed || '?'}</span>
                    <span style={s.teamName}>{teamA?.name || 'TBD'}</span>
                  </div>
                  <span style={s.vs}>vs</span>
                  <div>
                    <span style={s.teamName}>{teamB?.name || 'TBD'}</span>
                    <span style={{ ...s.seed, marginRight: 0, marginLeft: 8 }}>{teamB?.seed || '?'}</span>
                  </div>
                </div>

                {game.conductor_pick && (
                  <>
                    <div style={s.pickRow}>
                      <span style={s.pickLabel}>{'\u{1F3BC}'} Pick:</span>
                      <span style={s.pickValue}>{game.conductor_pick}</span>
                      <span style={{ marginLeft: 'auto', color: '#4A90D9', fontWeight: 600, fontSize: 13 }}>
                        {conf}%
                      </span>
                    </div>
                    <div style={s.confBar(conf)}>
                      <div style={s.confFill(conf, '#4A90D9')} />
                    </div>
                  </>
                )}

                {gVotes.length > 0 && (
                  <div style={s.voteSplit}>
                    {gVotes.map((v, i) => {
                      const agent = getAgent(v.agent_name);
                      return (
                        <div
                          key={i}
                          style={{
                            flex: 1,
                            background: agent.color,
                            opacity: 0.7,
                          }}
                          title={`${v.agent_name}: ${v.pick}`}
                        />
                      );
                    })}
                  </div>
                )}

                {!game.conductor_pick && (
                  <div style={{ color: '#444', fontSize: 13, marginTop: 8 }}>Pending analysis...</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
