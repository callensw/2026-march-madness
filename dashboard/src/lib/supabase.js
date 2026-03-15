import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabase = createClient(supabaseUrl, supabaseAnonKey)

// Table helpers for the March Madness schema
export const tables = {
  tournaments: 'mm_tournaments',
  teams: 'mm_teams',
  games: 'mm_games',
  agentVotes: 'mm_agent_votes',
  agentAccuracy: 'mm_agent_accuracy',
}
