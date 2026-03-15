import { useEffect, useState } from 'react';
import { supabase, tables } from '../lib/supabase';
import { AGENTS, getAgent } from '../lib/agents';

const s = {
  page: { padding: '32px 40px', maxWidth: 1100 },
  title: { fontSize: 28, fontWeight: 700, color: '#fff', margin: 0 },
  subtitle: { fontSize: 14, color: '#666', marginTop: 4, marginBottom: 32 },
  table: {
    width: '100%',
    borderCollapse: 'separate',
    borderSpacing: '0 6px',
  },
  th: {
    textAlign: 'left',
    padding: '8px 16px',
    fontSize: 11,
    color: '#555',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    fontWeight: 600,
  },
  thRight: {
    textAlign: 'right',
    padding: '8px 16px',
    fontSize: 11,
    color: '#555',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    fontWeight: 600,
  },
  td: (first, last) => ({
    padding: '14px 16px',
    background: '#141414',
    borderTop: '1px solid #1e1e1e',
    borderBottom: '1px solid #1e1e1e',
    borderLeft: first ? '1px solid #1e1e1e' : 'none',
    borderRight: last ? '1px solid #1e1e1e' : 'none',
    borderRadius: first ? '10px 0 0 10px' : last ? '0 10px 10px 0' : 0,
  }),
  rank: { fontSize: 20, fontWeight: 700, color: '#333', width: 50 },
  rankGold: { fontSize: 20, fontWeight: 700, color: '#E8D44D' },
  rankSilver: { fontSize: 20, fontWeight: 700, color: '#aaa' },
  rankBronze: { fontSize: 20, fontWeight: 700, color: '#cd7f32' },
  agentCell: { display: 'flex', alignItems: 'center', gap: 10 },
  avatar: (color) => ({
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 32,
    height: 32,
    borderRadius: '50%',
    background: color + '22',
    border: `2px solid ${color}`,
    fontSize: 16,
  }),
  agentName: (color) => ({ fontWeight: 600, color }),
  agentRole: { fontSize: 11, color: '#666' },
  accPct: (pct) => ({
    fontWeight: 700,
    fontSize: 16,
    color: pct >= 70 ? '#4ade80' : pct >= 50 ? '#FFB347' : '#ef4444',
    textAlign: 'right',
  }),
  streak: (val) => ({
    fontWeight: 600,
    color: val > 0 ? '#4ade80' : val < 0 ? '#ef4444' : '#555',
    textAlign: 'right',
    fontSize: 14,
  }),
  cardsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
    gap: 16,
    marginTop: 40,
  },
  profileCard: (color) => ({
    background: '#141414',
    border: '1px solid #1e1e1e',
    borderTop: `3px solid ${color}`,
    borderRadius: 12,
    padding: 24,
  }),
  chartSection: { marginTop: 40 },
  barRow: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 },
  barLabel: { width: 120, fontSize: 13, color: '#aaa', textAlign: 'right', flexShrink: 0 },
  barOuter: { flex: 1, height: 24, borderRadius: 6, background: '#1e1e1e', overflow: 'hidden' },
  barInner: (pct, color) => ({
    height: '100%',
    width: `${pct}%`,
    background: color,
    borderRadius: 6,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    paddingRight: 8,
    fontSize: 12,
    fontWeight: 600,
    color: '#fff',
    transition: 'width 0.5s',
  }),
  loading: { padding: '80px 40px', textAlign: 'center', color: '#555', fontSize: 16 },
};

const DESCRIPTIONS = {
  "Tempo Hawk": "Analyzes pace of play, offensive/defensive efficiency ratings, and tempo-free metrics. Believes the game is won and lost in transition.",
  "Iron Curtain": "Obsessed with defensive metrics -- adjusted defensive efficiency, opponent FG%, blocks, steals. If you can't stop them, you can't beat them.",
  "Glass Cannon": "Lives and dies by three-point shooting, offensive explosiveness, and scoring runs. Favors teams that can light it up from deep.",
  "Road Dog": "Old-school scouting eye. Watches tape, evaluates toughness, coaching, clutch play, and intangibles that don't show up in box scores.",
  "Whisper": "The intel agent. Tracks injury reports, lineup changes, travel fatigue, locker room vibes, and betting line movements.",
  "Oracle": "Pure historical analysis. Seed matchup history, conference performance trends, and base rates for upsets by round.",
  "The Conductor": "Synthesizes all agent perspectives into a final pick. Weighs confidence levels, resolves disagreements, and makes the call.",
};

export default function AgentLeaderboard() {
  const [accuracy, setAccuracy] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      const { data } = await supabase.from(tables.agentAccuracy).select('*');
      if (data) setAccuracy(data);
      setLoading(false);
    }
    fetchData();
  }, []);

  if (loading) return <div style={s.loading}>Loading agent data...</div>;

  // Sort by accuracy descending
  const sorted = [...accuracy].sort((a, b) => {
    const accA = a.total_picks > 0 ? a.correct_picks / a.total_picks : 0;
    const accB = b.total_picks > 0 ? b.correct_picks / b.total_picks : 0;
    return accB - accA;
  });

  const rankStyle = (i) => {
    if (i === 0) return s.rankGold;
    if (i === 1) return s.rankSilver;
    if (i === 2) return s.rankBronze;
    return s.rank;
  };

  return (
    <div style={s.page}>
      <h1 style={s.title}>Agent Leaderboard</h1>
      <p style={s.subtitle}>Performance rankings for all swarm agents</p>

      {sorted.length === 0 ? (
        <div style={{ background: '#141414', border: '1px solid #1e1e1e', borderRadius: 12, padding: 60, textAlign: 'center', color: '#555' }}>
          No accuracy data available yet.
        </div>
      ) : (
        <>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>#</th>
                <th style={s.th}>Agent</th>
                <th style={s.thRight}>Correct</th>
                <th style={s.thRight}>Total</th>
                <th style={s.thRight}>Accuracy</th>
                <th style={s.thRight}>Streak</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((agent, i) => {
                const agentMeta = getAgent(agent.agent_name);
                const pct = agent.total_picks > 0
                  ? ((agent.correct_picks / agent.total_picks) * 100).toFixed(1)
                  : '0.0';

                return (
                  <tr key={agent.agent_name}>
                    <td style={s.td(true, false)}>
                      <span style={rankStyle(i)}>{i + 1}</span>
                    </td>
                    <td style={s.td(false, false)}>
                      <div style={s.agentCell}>
                        <div style={s.avatar(agentMeta.color)}>{agentMeta.emoji}</div>
                        <div>
                          <div style={s.agentName(agentMeta.color)}>{agent.agent_name}</div>
                          <div style={s.agentRole}>{agentMeta.role}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ ...s.td(false, false), textAlign: 'right', fontSize: 15, color: '#e0e0e0' }}>
                      {agent.correct_picks || 0}
                    </td>
                    <td style={{ ...s.td(false, false), textAlign: 'right', fontSize: 15, color: '#888' }}>
                      {agent.total_picks || 0}
                    </td>
                    <td style={{ ...s.td(false, false), ...s.accPct(parseFloat(pct)) }}>
                      {pct}%
                    </td>
                    <td style={{ ...s.td(false, true), ...s.streak(agent.streak || 0) }}>
                      {agent.streak > 0 ? `W${agent.streak}` : agent.streak < 0 ? `L${Math.abs(agent.streak)}` : '-'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Bar chart */}
          <div style={s.chartSection}>
            <h2 style={{ fontSize: 18, fontWeight: 600, color: '#fff', marginBottom: 16 }}>Accuracy Comparison</h2>
            {sorted.map((agent) => {
              const agentMeta = getAgent(agent.agent_name);
              const pct = agent.total_picks > 0
                ? ((agent.correct_picks / agent.total_picks) * 100).toFixed(1)
                : 0;

              return (
                <div key={agent.agent_name} style={s.barRow}>
                  <div style={s.barLabel}>
                    {agentMeta.emoji} {agent.agent_name}
                  </div>
                  <div style={s.barOuter}>
                    <div style={s.barInner(pct, agentMeta.color)}>
                      {pct > 10 ? `${pct}%` : ''}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Profile cards */}
      <div style={s.cardsGrid}>
        {Object.entries(AGENTS).map(([name, meta]) => (
          <div key={name} style={s.profileCard(meta.color)}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <div style={s.avatar(meta.color)}>{meta.emoji}</div>
              <div>
                <div style={{ fontWeight: 700, color: meta.color, fontSize: 15 }}>{name}</div>
                <div style={{ fontSize: 12, color: '#666' }}>{meta.role}</div>
              </div>
            </div>
            <p style={{ fontSize: 13, color: '#888', lineHeight: 1.6 }}>
              {DESCRIPTIONS[name] || 'No description available.'}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
