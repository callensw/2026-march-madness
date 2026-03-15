import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { supabase, tables } from '../lib/supabase';
import { AGENTS, getAgent } from '../lib/agents';

const s = {
  page: { padding: '32px 40px', maxWidth: 900 },
  back: { color: '#4A90D9', textDecoration: 'none', fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 20 },
  matchupCard: {
    background: '#141414',
    border: '1px solid #1e1e1e',
    borderRadius: 12,
    padding: 24,
    marginBottom: 24,
    textAlign: 'center',
  },
  matchupTeams: { display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 24, marginBottom: 8 },
  teamBlock: { textAlign: 'center' },
  teamSeed: { fontSize: 14, color: '#666', marginBottom: 2 },
  teamName: { fontSize: 22, fontWeight: 700, color: '#fff' },
  vs: { fontSize: 14, color: '#444' },
  round: { fontSize: 13, color: '#555', marginTop: 8 },
  sectionTitle: { fontSize: 16, fontWeight: 600, color: '#fff', marginBottom: 16, marginTop: 8 },
  thread: { display: 'flex', flexDirection: 'column', gap: 16 },
  voteCard: (color, isConductor) => ({
    background: isConductor ? '#1a1a2e' : '#141414',
    border: `1px solid ${isConductor ? '#333366' : '#1e1e1e'}`,
    borderLeft: `4px solid ${color}`,
    borderRadius: 12,
    padding: 20,
  }),
  avatar: (color) => ({
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 36,
    height: 36,
    borderRadius: '50%',
    background: color + '22',
    border: `2px solid ${color}`,
    fontSize: 18,
    marginRight: 12,
  }),
  agentHeader: { display: 'flex', alignItems: 'center', marginBottom: 12 },
  agentName: (color) => ({ fontSize: 15, fontWeight: 700, color }),
  agentRole: { fontSize: 12, color: '#666', marginLeft: 8 },
  pickBadge: (agrees) => ({
    display: 'inline-block',
    padding: '3px 10px',
    borderRadius: 20,
    fontSize: 12,
    fontWeight: 600,
    background: agrees ? 'rgba(74,222,128,0.12)' : 'rgba(239,68,68,0.12)',
    color: agrees ? '#4ade80' : '#ef4444',
    border: `1px solid ${agrees ? '#4ade8044' : '#ef444444'}`,
    marginLeft: 'auto',
  }),
  reasoning: { fontSize: 14, color: '#aaa', lineHeight: 1.6, marginTop: 8 },
  keyStat: { fontSize: 12, color: '#666', marginTop: 6, fontStyle: 'italic' },
  confBarOuter: { height: 6, borderRadius: 3, background: '#1e1e1e', marginTop: 8 },
  confBarInner: (pct, color) => ({
    height: '100%',
    borderRadius: 3,
    width: `${pct}%`,
    background: color,
    transition: 'width 0.3s',
  }),
  confLabel: { fontSize: 11, color: '#555', marginTop: 2, textAlign: 'right' },
  verdict: {
    background: '#141428',
    border: '2px solid #333366',
    borderRadius: 16,
    padding: 28,
    marginTop: 32,
    textAlign: 'center',
  },
  verdictTitle: { fontSize: 14, color: '#888', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 12 },
  verdictPick: { fontSize: 28, fontWeight: 700, color: '#fff', marginBottom: 16 },
  bigMeter: {
    height: 16,
    borderRadius: 8,
    background: '#1e1e1e',
    maxWidth: 400,
    margin: '0 auto',
    overflow: 'hidden',
  },
  tallyBar: {
    display: 'flex',
    height: 24,
    borderRadius: 6,
    overflow: 'hidden',
    marginTop: 32,
    gap: 2,
  },
  tallySegment: (color, pct) => ({
    width: `${pct}%`,
    background: color,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 11,
    fontWeight: 600,
    color: '#fff',
    minWidth: pct > 10 ? 'auto' : 0,
    overflow: 'hidden',
  }),
  loading: { padding: '80px 40px', textAlign: 'center', color: '#555', fontSize: 16 },
};

export default function DebateView() {
  const { gameId } = useParams();
  const [game, setGame] = useState(null);
  const [teams, setTeams] = useState({});
  const [votes, setVotes] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      const [gameRes, votesRes, teamsRes] = await Promise.all([
        supabase.from(tables.games).select('*').eq('id', gameId).single(),
        supabase.from(tables.agentVotes).select('*').eq('game_id', gameId),
        supabase.from(tables.teams).select('*'),
      ]);
      if (gameRes.data) setGame(gameRes.data);
      if (votesRes.data) setVotes(votesRes.data);
      if (teamsRes.data) {
        const map = {};
        teamsRes.data.forEach((t) => { map[t.id] = t; });
        setTeams(map);
      }
      setLoading(false);
    }
    fetchData();
  }, [gameId]);

  if (loading) return <div style={s.loading}>Loading debate...</div>;
  if (!game) return <div style={s.loading}>Game not found.</div>;

  const teamA = teams[game.team_a_id];
  const teamB = teams[game.team_b_id];
  const conductorVote = votes.find((v) => v.agent_name === 'The Conductor');
  const agentVotes = votes.filter((v) => v.agent_name !== 'The Conductor');

  // Vote tally
  const tally = {};
  votes.forEach((v) => {
    if (!v.pick) return;
    tally[v.pick] = (tally[v.pick] || 0) + 1;
  });
  const totalVotes = Object.values(tally).reduce((a, b) => a + b, 0);

  return (
    <div style={s.page}>
      <Link to="/" style={s.back}>{'\u2190'} Back to Dashboard</Link>

      <div style={s.matchupCard}>
        <div style={s.matchupTeams}>
          <div style={s.teamBlock}>
            <div style={s.teamSeed}>#{teamA?.seed || '?'} seed</div>
            <div style={s.teamName}>{teamA?.name || 'TBD'}</div>
          </div>
          <span style={s.vs}>vs</span>
          <div style={s.teamBlock}>
            <div style={s.teamSeed}>#{teamB?.seed || '?'} seed</div>
            <div style={s.teamName}>{teamB?.name || 'TBD'}</div>
          </div>
        </div>
        <div style={s.round}>
          Round {game.round || '?'} {teamA?.region ? `\u00B7 ${teamA.region} Region` : ''}
        </div>
      </div>

      <h2 style={s.sectionTitle}>Agent Debate</h2>

      {agentVotes.length === 0 && (
        <div style={{ background: '#141414', border: '1px solid #1e1e1e', borderRadius: 12, padding: 40, textAlign: 'center', color: '#555' }}>
          No agent votes yet for this game.
        </div>
      )}

      <div style={s.thread}>
        {agentVotes.map((vote) => {
          const agent = getAgent(vote.agent_name);
          const agrees = game.conductor_pick && vote.pick === game.conductor_pick;

          return (
            <div key={vote.id || vote.agent_name} style={s.voteCard(agent.color, false)}>
              <div style={s.agentHeader}>
                <div style={s.avatar(agent.color)}>{agent.emoji}</div>
                <div>
                  <div style={s.agentName(agent.color)}>{vote.agent_name}</div>
                  <div style={s.agentRole}>{agent.role}</div>
                </div>
                {game.conductor_pick && (
                  <div style={s.pickBadge(agrees)}>
                    {agrees ? 'Agrees' : 'Dissents'}
                  </div>
                )}
              </div>

              <div style={{ fontSize: 14, color: '#e0e0e0', fontWeight: 600, marginBottom: 4 }}>
                Pick: {vote.pick || 'N/A'}
              </div>

              {vote.confidence != null && (
                <>
                  <div style={s.confBarOuter}>
                    <div style={s.confBarInner(vote.confidence, agent.color)} />
                  </div>
                  <div style={s.confLabel}>{vote.confidence}% confidence</div>
                </>
              )}

              {vote.reasoning && <div style={s.reasoning}>{vote.reasoning}</div>}
              {vote.key_stat && <div style={s.keyStat}>Key stat: {vote.key_stat}</div>}
            </div>
          );
        })}
      </div>

      {/* Conductor Verdict */}
      {game.conductor_pick && (
        <div style={s.verdict}>
          <div style={s.verdictTitle}>{'\u{1F3BC}'} The Conductor's Verdict</div>
          <div style={s.verdictPick}>{game.conductor_pick}</div>
          {game.conductor_confidence != null && (
            <>
              <div style={s.bigMeter}>
                <div
                  style={{
                    height: '100%',
                    borderRadius: 8,
                    width: `${game.conductor_confidence}%`,
                    background: 'linear-gradient(90deg, #4A90D9, #4ade80)',
                  }}
                />
              </div>
              <div style={{ fontSize: 13, color: '#888', marginTop: 6 }}>
                {game.conductor_confidence}% confidence
              </div>
            </>
          )}
          {game.conductor_reasoning && (
            <div style={{ fontSize: 14, color: '#aaa', marginTop: 16, maxWidth: 500, margin: '16px auto 0', lineHeight: 1.6 }}>
              {game.conductor_reasoning}
            </div>
          )}
        </div>
      )}

      {/* Vote Tally */}
      {totalVotes > 0 && (
        <div style={{ marginTop: 32 }}>
          <h2 style={s.sectionTitle}>Vote Tally</h2>
          <div style={s.tallyBar}>
            {Object.entries(tally).map(([pick, count]) => {
              const pct = (count / totalVotes) * 100;
              const isTeamA = pick === teamA?.name;
              return (
                <div key={pick} style={s.tallySegment(isTeamA ? '#4A90D9' : '#D94A4A', pct)}>
                  {pct > 15 ? `${pick} (${count})` : ''}
                </div>
              );
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#555', marginTop: 6 }}>
            {Object.entries(tally).map(([pick, count]) => (
              <span key={pick}>{pick}: {count} vote{count !== 1 ? 's' : ''}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
