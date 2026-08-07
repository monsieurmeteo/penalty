export interface Match {
  id: string;
  dom: string;
  ext: string;
  league: string;
  start_iso: string;
  date_str: string;
  status: 'FINISHED' | 'LIVE' | 'UPCOMING';
  score_dom: number | null;
  score_ext: number | null;
  is_selected: boolean;
  selection_status: 'WON' | 'LOST' | 'PENDING';
  rejection_reason: string | null;
  s22: number | null;
  over25: number | null;
  buteur_name: string | null;
  buteur_cote: number | null;
  profit_units: number;
  // Live specific
  minute?: string;
  period_label?: string;
}

export interface Summary {
  total_live: number;
  total_scanned_upcoming: number;
  total_selected_upcoming: number;
  total_history_bets: number;
  total_wins: number;
  total_losses: number;
  win_rate_over25: number;
  total_profit_units: number;
  roi_pct: number;
  initial_bankroll: number;
  current_bankroll: number;
  avg_odds_over25_global: number;
  avg_odds_s22_global: number;
  last_update: string;
}

export interface BankrollPoint {
  step: number;
  date: string;
  match: string;
  profit_cumul: number;
  bankroll: number;
  result: string;
}

export interface LeagueStat {
  league: string;
  total: number;
  won: number;
  lost: number;
  win_rate: number;
  profit: number;
  roi: number;
}

export interface DashboardData {
  summary: Summary;
  bankroll_curve: BankrollPoint[];
  league_stats: LeagueStat[];
  matches: Match[];
}
