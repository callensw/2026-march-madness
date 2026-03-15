import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { supabase, tables } from '../lib/supabase';
import { getAgent } from '../lib/agents';

const s = {
  page: { padding: '32px 40px', maxWidth: 1000 },
  title: { fontSize: 28, fontWeight: 700, color: '#fff', margin: 0 },
  subtitle: { fontSize: 14, color: '#666', marginTop: 4, marginBottom: 32 },
  card: {
    background: '#141414',
    border: '1px solid #1e1e1e',
    borderRadius: 12,
    padding: 20,
    marginBottom: 12,
    display: 'flex',
    alignItems: 'flex-start',
    gap: 16,
    transition: 'border-color 0.15s',
  },
  rank: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 40,
    height: 40,
    borderRadius: 10,
    background: '#1e1e1e',
    fontSize: 16,
    fontWeight: 700,
    color: '#FFB347',
    flexShrink: 0,
  },
  body: { flex: 1, minWidth: 0 },
  matchup: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  teamBadge: (isUnderdog) => ({
    padding: '4px 12px',
    borderRadius: 6,
    background: isUnderdog ? 'rgba(255,179,71,0.12)' : 'rgba(255,255,255,0.04)',
    border: isUnderdog ? '1px solid rgba(255,179,71,0.3)' : '1px solid #1e1e1e',
    fontSize: 14,
    fontWeight: 600,
    color: isUnderdog ? '#FFB347' : '#e0e0e0',
  }),
  seed: { fontSize: 11, color: '#666', marginRight: 4 },
  vs: { fontSize: 12, color: '#444' },
  meta: { display: 'flex', gap: 20, marginTop: 10, flexWrap: 'wrap' },
  metaItem: { fontSize: 13 },
  metaLabel: { color: '#555' },
  metaValue: { color: '#e0e0e0', fontWeight: 600 },
  probBar: {
    width: 120,
    height: 6,
    borderRadius: 3,
    background: '#1e1e1e',
    overflow: 'hidden',
    marginTop: 8,
    flexShrink: 0,
  },
  probFill: (pct) => ({
    height: '100%',
    width: `${pct}%`,
    borderRadius: 3,
    background: pct >= 70 ? '#ef4444' : pct >= 40 ? '#FFB347' : '#E8D44D',
  }),
  probLabel: { fontSize: 11, color: '#666', marginTop: 2, textAlign: 'center' },
  agentChips: { display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 8 },
  chip: (color) => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '2px 8px',
    borderRadius: 12,
    fontSize: 11,
    background: color + '18',
    color: color,
    border: `1px solid ${color}33`,
  }),
  empty: {
    background: '#141414',
    border: '1px solid #1e1e1e',
    borderRadius: 12,
    padding: 60,
    textAlign: 'center',
    color: '#555',
  },
  link: { textDecoration: 'none', color: 'inherit', display: 'block' },
  loading: { padding: '80px 40px', textAlign: 'center', color: '#555', fontSize: 16 },
};

export default function UpsetWatch() {
  const [upsets, setUpsets] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      const [gamesRes, teamsRes, votesRes] = await Promise.all([
        supabase.from(tables.games).select('*'),
        supabase.from(tables.teams).select('*'),
        supabase.from(tables.agentVotes).select('*'),
      ]);

      if (!gamesRes.data || !teamsRes.data) {
        setLoading(false);
        return;
      }

      const teamsMap = {};
      teamsRes.data.forEach((t) => { teamsMap[t.id] = t; });

      const votesByGame = {};
      (votesRes.data || []).forEach((v) => {
        if (!votesByGame[v.game_id]) votesByGame[v.game_id] = [];
        votesByGame[v.game_id].push(v);
      });

      const upsetList = [];
      gamesRes.data.forEach((game) => {
        const teamA = teamsMap[game.team_a_id];
        const teamB = teamsMap[game.team_b_id];
        if (!teamA || !teamB) return;

        let isUpset = false;
        let upsetProb = 0;

        // Conductor picked the lower-seeded team (higher seed number)
        if (game.conductor_pick) {
          const pickedTeam = game.conductor_pick === teamA.name ? teamA : teamB;
          const otherTeam = game.conductor_pick === teamA.name ? teamB : teamA;
          if (pickedTeam.seed > otherTeam.seed) {
            isUpset = true;
            upsetProb = game.conductor_confidence || 50;
          }
        }

        // Low confidence game
        if (game.conductor_confidence && game.conductor_confidence < 60) {
          isUpset = true;
          upsetProb = Math.max(upsetProb, 100 - (game.conductor_confidence || 50));
        }

        if (isUpset) {
          const gVotes = votesByGame[game.id] || [];
          // Find agents that backed the underdog (higher seed)
          const higherSeedTeam = teamA.seed > teamB.seed ? teamA : teamB;
          const underdogBackers = gVotes.filter((v) => v.pick === higherSeedTeam.name);

          upsetList.push({
            game,
            teamA,
            teamB,
            upsetProb,
            underdogBackers,
            higherSeedTeam,
            lowerSeedTeam: teamA.seed <= teamB.seed ? teamA : teamB,
          });
        }
      });

      upsetList.sort((a, b) => b.upsetProb - a.upsetProb);
      setUpsets(upsetList);
      setLoading(false);
    }
    fetchData();
  }, []);

  if (loading) return <div style={s.loading}>Loading upset data...</div>;

  return (
    <div style={s.page}>
      <h1 style={s.title}>{'\u{1F525}'} Upset Watch</h1>
      <p style={s.subtitle}>Games where the swarm sees a potential upset or low confidence</p>

      {upsets.length === 0 ? (
        <div style={s.empty}>
          No upset alerts yet. Check back when games have been analyzed.
        </div>
      ) : (
        upsets.map((u, i) => (
          <Link key={u.game.id} to={`/debate/${u.game.id}`} style={s.link}>
            <div
              style={s.card}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#333'; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#1e1e1e'; }}
            >
              <div style={s.rank}>{i + 1}</div>

              <div style={s.body}>
                <div style={s.matchup}>
                  <span style={s.teamBadge(u.teamA.seed > u.teamB.seed)}>
                    <span style={s.seed}>#{u.teamA.seed}</span> {u.teamA.name}
                  </span>
                  <span style={s.vs}>vs</span>
                  <span style={s.teamBadge(u.teamB.seed > u.teamA.seed)}>
                    <span style={s.seed}>#{u.teamB.seed}</span> {u.teamB.name}
                  </span>
                </div>

                <div style={s.meta}>
                  <div style={s.metaItem}>
                    <span style={s.metaLabel}>Pick: </span>
                    <span style={s.metaValue}>{u.game.conductor_pick || 'Pending'}</span>
                  </div>
                  <div style={s.metaItem}>
                    <span style={s.metaLabel}>Confidence: </span>
                    <span style={{ ...s.metaValue, color: (u.game.conductor_confidence || 0) < 60 ? '#FFB347' : '#e0e0e0' }}>
                      {u.game.conductor_confidence || '--'}%
                    </span>
                  </div>
                  <div style={s.metaItem}>
                    <span style={s.metaLabel}>Seed diff: </span>
                    <span style={s.metaValue}>
                      {Math.abs(u.teamA.seed - u.teamB.seed)}
                    </span>
                  </div>
                </div>

                {u.underdogBackers.length > 0 && (
                  <div style={s.agentChips}>
                    <span style={{ fontSize: 11, color: '#555', marginRight: 4, lineHeight: '22px' }}>
                      Underdog backers:
                    </span>
                    {u.underdogBackers.map((v) => {
                      const agent = getAgent(v.agent_name);
                      return (
                        <span key={v.agent_name} style={s.chip(agent.color)}>
                          {agent.emoji} {v.agent_name}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>

              <div style={{ flexShrink: 0, textAlign: 'center' }}>
                <div style={s.probBar}>
                  <div style={s.probFill(u.upsetProb)} />
                </div>
                <div style={s.probLabel}>{u.upsetProb}% upset</div>
              </div>
            </div>
          </Link>
        ))
      )}
    </div>
  );
}
