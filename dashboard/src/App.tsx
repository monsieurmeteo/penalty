import { useState, useEffect } from 'react';
import type { DashboardData, Match } from './types';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts';

// ── SVG ICONS ─────────────────────────────────────────────────────────────────
const Icon = {
  Refresh: (c: string) => (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
    </svg>
  ),
  Trending: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>
    </svg>
  ),
  Pct: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="5" x2="5" y2="19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>
    </svg>
  ),
  Target: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>
    </svg>
  ),
  Layers: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>
    </svg>
  ),
  Search: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
    </svg>
  ),
  Check: (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  ),
  X: (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  ),
  Clock: (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
    </svg>
  ),
  Star: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
    </svg>
  ),
  Ban: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
    </svg>
  ),
  History: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/>
      <line x1="12" y1="7" x2="12" y2="12"/><line x1="12" y1="12" x2="16" y2="14"/>
    </svg>
  ),
  Award: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>
    </svg>
  ),
};

// ── HELPERS ───────────────────────────────────────────────────────────────────
const fmtCote = (v: number | null | undefined) => v != null ? v.toFixed(2) : 'N/A';

function getLeagueFlag(league: string) {
  const map: Record<string, string> = {
    'Allemagne': '🇩🇪', 'Norvege': '🇳🇴', 'Pays Bas': '🇳🇱', 'Pologne': '🇵🇱',
    'Hongrie': '🇭🇺', 'Estonie': '🇪🇪', 'Finlande': '🇫🇮', 'Japon': '🇯🇵',
    'Amerique': '🇺🇸', 'Pays De Galles': '🏴󠁧󠁢󠁷󠁬󠁳󠁿', 'Autriche': '🇦🇹', 'Danemark': '🇩🇰',
    'France': '🇫🇷', 'Angleterre': '🏴󠁧󠁢󠁥󠁮󠁧󠁿', 'Espagne': '🇪🇸', 'Italie': '🇮🇹',
    'Portugal': '🇵🇹', 'Belgique': '🇧🇪', 'Suisse': '🇨🇭', 'Croatie': '🇭🇷',
    'Suede': '🇸🇪', 'Grece': '🇬🇷', 'Turquie': '🇹🇷', 'Roumanie': '🇷🇴',
    'Tcheque': '🇨🇿', 'Slovaquie': '🇸🇰', 'Serbie': '🇷🇸', 'Bresil': '🇧🇷',
    'Argentine': '🇦🇷', 'Mexique': '🇲🇽', 'Australie': '🇦🇺', 'Coree': '🇰🇷',
    'Chine': '🇨🇳', 'Islande': '🇮🇸', 'Chypre': '🇨🇾', 'Israel': '🇮🇱',
    'Irlande': '🇮🇪', 'Ecosse': '🏴󠁧󠁢󠁳󠁣󠁴󠁿', 'Bulgarie': '🇧🇬',
  };
  for (const [k, v] of Object.entries(map)) {
    if (league.toLowerCase().includes(k.toLowerCase())) return v;
  }
  return '⚽';
}

// ── CUSTOM TOOLTIP FOR CHART ──────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const won = d.result === 'WON';
  return (
    <div style={{ background: '#0c1120', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '10px 14px', fontSize: 12 }}>
      <div style={{ color: '#64748b', marginBottom: 6, fontWeight: 600 }}>Paris #{d.step} — {label}</div>
      <div style={{ fontWeight: 800, fontSize: 15, color: won ? '#4ade80' : '#f87171' }}>
        {won ? '✅' : '❌'} {d.match}
      </div>
      <div style={{ marginTop: 6, color: '#94a3b8' }}>
        Profit cumulé : <strong style={{ color: d.profit_cumul >= 0 ? '#4ade80' : '#f87171' }}>
          {d.profit_cumul >= 0 ? `+${d.profit_cumul}` : d.profit_cumul} U
        </strong>
      </div>
    </div>
  );
}

// ── LIVE PROGRESS BAR ─────────────────────────────────────────────────────────
function LiveProgressBar({ minute }: { minute: string }) {
  const pct = Math.min((parseInt(minute) / 90) * 100, 100);
  return (
    <div className="progress-bar-container">
      <div className="progress-bar-bg">
        <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── LIVE CARD ─────────────────────────────────────────────────────────────────
function LiveCard({ m }: { m: Match }) {
  const buts = (m.score_dom ?? 0) + (m.score_ext ?? 0);
  const validated = m.selection_status === 'WON';
  return (
    <div className="live-card">
      <div className="live-card-header">
        <div className="live-badge">
          <div className="live-badge-dot" />
          LIVE
        </div>
        <span className="live-league">{m.league}</span>
        <span className="live-minute">{m.minute}</span>
      </div>

      <div className="live-scoreboard">
        <div className="team-block">
          <div className="team-name">{m.dom}</div>
        </div>
        <div className="score-block">
          <div className="score-display">
            <span style={{ color: '#f1f5f9' }}>{m.score_dom}</span>
            <span className="score-sep"> – </span>
            <span style={{ color: '#f1f5f9' }}>{m.score_ext}</span>
          </div>
          <div className="score-label">{buts} but{buts > 1 ? 's' : ''} • {m.period_label}</div>
        </div>
        <div className="team-block">
          <div className="team-name">{m.ext}</div>
        </div>
      </div>

      <div className="live-card-footer">
        <div className="live-odds-row">
          <span className="odds-pill o25">Over 2.5 · {fmtCote(m.over25)}</span>
          <span className="odds-pill s22">BTTS Oui · {fmtCote(m.btts_oui)}</span>
        </div>
        {validated ? (
          <span className="live-status-pill won">✅ Validé !</span>
        ) : (
          <span className="live-status-pill in-progress">⏳ En cours…</span>
        )}
      </div>

      <div style={{ padding: '0 16px 14px' }}>
        <LiveProgressBar minute={m.minute ?? '0'} />
      </div>
    </div>
  );
}

// ── MAIN APP ──────────────────────────────────────────────────────────────────
export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'selected' | 'rejected' | 'history' | 'leagues'>('selected');
  const [search, setSearch] = useState('');
  const [leagueFilter, setLeagueFilter] = useState('ALL');

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch('./data/matches.json?t=' + Date.now());
      if (!r.ok) throw new Error('HTTP ' + r.status);
      setData(await r.json());
      setError(null);
    } catch (e: any) {
      setError(e.message ?? 'Erreur réseau');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // Auto-refresh every 60s for live scores
    const interval = setInterval(() => {
      load();
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  if (!data && loading) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', gap: 16 }}>
      <div style={{ width: 50, height: 50, border: '3px solid rgba(240,180,41,0.2)', borderTop: '3px solid #f0b429', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
      <p style={{ color: '#64748b', fontSize: 14 }}>Synchronisation Unibet en cours…</p>
    </div>
  );

  if (!data) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', gap: 12 }}>
      <p style={{ color: '#f87171', fontSize: 18, fontWeight: 700 }}>Erreur : {error}</p>
      <button onClick={load} className="refresh-btn">Réessayer</button>
    </div>
  );

  const { summary, bankroll_curve, league_stats, matches } = data;
  const liveMatches = matches.filter(m => m.status === 'LIVE');
  const upcomingSelected = matches.filter(m => m.status === 'UPCOMING' && m.is_selected);
  const upcomingRejected = matches.filter(m => m.status === 'UPCOMING' && !m.is_selected);
  const historyMatches = matches.filter(m => m.status === 'FINISHED');
  const allLeagues = Array.from(new Set(matches.map(m => m.league))).sort();

  const filter = (list: Match[]) => list.filter(m => {
    const s = search.toLowerCase();
    return (
      (!s || m.dom.toLowerCase().includes(s) || m.ext.toLowerCase().includes(s) || m.league.toLowerCase().includes(s)) &&
      (leagueFilter === 'ALL' || m.league === leagueFilter)
    );
  });

  const lastUpdate = new Date(summary.last_update).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });

  return (
    <>
      {/* ─── HEADER ───────────────────────────────── */}
      <header className="header">
        <div className="header-inner">
          <div className="logo">
            <div className="logo-icon">⚽</div>
            <div>
              <div className="logo-text">OVER 2.5 ANALYTICS <span className="logo-badge">PRO</span></div>
            </div>
          </div>
          <div className="header-right">
            {liveMatches.length > 0 && (
              <div className="live-indicator">
                <div className="live-dot" />
                {liveMatches.length} match{liveMatches.length > 1 ? 's' : ''} en direct
              </div>
            )}
            <button className={`refresh-btn ${loading ? 'spinning' : ''}`} onClick={load}>
              {Icon.Refresh(loading ? '#f0b429' : 'currentColor')}
              Actualiser
            </button>
          </div>
        </div>
      </header>

      {/* ─── MAIN CONTENT ─────────────────────────── */}
      <div className="main">

        {/* ── KPIs ────────────────────────────────── */}
        <div className="kpi-grid">
          <div className="kpi-card gold">
            <div className="kpi-header">
              <span className="kpi-label">Profit Total & Capital</span>
              <div className="kpi-icon gold">{Icon.Trending}</div>
            </div>
            <div className="kpi-value gold">+{summary.total_profit_units} U</div>
            <div className="kpi-sub">
              Capital actuel : <span>{summary.current_bankroll} U</span>
              <span style={{ color: '#22c55e' }}>+{(summary.total_profit_units * 10).toFixed(0)} €</span>
            </div>
          </div>

          <div className="kpi-card green">
            <div className="kpi-header">
              <span className="kpi-label">ROI / Yield Net</span>
              <div className="kpi-icon green">{Icon.Pct}</div>
            </div>
            <div className="kpi-value green">+{summary.roi_pct}%</div>
            <div className="kpi-sub">
              Paris joués : <span>{summary.total_history_bets}</span>
              <span style={{ color: '#4ade80' }}>{summary.total_wins}V / {summary.total_losses}D</span>
            </div>
          </div>

          <div className="kpi-card blue">
            <div className="kpi-header">
              <span className="kpi-label">Taux de Réussite Over 2.5</span>
              <div className="kpi-icon blue">{Icon.Target}</div>
            </div>
            <div className="kpi-value white">{summary.win_rate_over25}<span style={{ fontSize: 22, color: '#60a5fa', marginLeft: 4 }}>%</span></div>
            <div className="kpi-sub">
              BTTS Oui &lt; Non &amp; Over 2.5 &lt; Under 2.5 <span style={{ color: '#60a5fa' }}>Méthode Validée ✓</span>
            </div>
          </div>

          <div className="kpi-card purple">
            <div className="kpi-header">
              <span className="kpi-label">Moyenne Cotes Marché</span>
              <div className="kpi-icon purple">{Icon.Layers}</div>
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
              <div style={{ flex: 1, background: 'rgba(59,130,246,0.08)', borderRadius: 10, border: '1px solid rgba(59,130,246,0.15)', padding: '10px 12px' }}>
                <div style={{ fontSize: 10, color: '#64748b', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px' }}>Over 2.5</div>
                <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 26, fontWeight: 800, color: '#60a5fa' }}>{summary.avg_odds_over25_global}</div>
              </div>
              <div style={{ flex: 1, background: 'rgba(240,180,41,0.07)', borderRadius: 10, border: '1px solid rgba(240,180,41,0.15)', padding: '10px 12px' }}>
                <div style={{ fontSize: 10, color: '#64748b', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px' }}>BTTS Oui</div>
                <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 26, fontWeight: 800, color: '#f0b429' }}>{summary.avg_odds_btts_global}</div>
              </div>
            </div>
          </div>
        </div>

        {/* ── CHARTS ROW ───────────────────────────── */}
        <div className="charts-row">
          {/* Bankroll Curve */}
          <div className="chart-card">
            <div className="chart-title">📈 Courbe de Capital (Bankroll)</div>
            <div className="chart-sub">Évolution du profit cumulé sur les {bankroll_curve.length} derniers paris sélectionnés</div>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={bankroll_curve} margin={{ top: 4, right: 10, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="date" stroke="#334155" fontSize={10} tickLine={false} tick={{ fill: '#475569' }} interval={Math.floor(bankroll_curve.length / 6)} />
                <YAxis stroke="#334155" fontSize={10} tickLine={false} tick={{ fill: '#475569' }} />
                <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" />
                <Tooltip content={<ChartTooltip />} />
                <Line
                  type="monotone"
                  dataKey="profit_cumul"
                  stroke="#f0b429"
                  strokeWidth={2.5}
                  dot={(props: any) => {
                    const won = props.payload?.result === 'WON';
                    return <circle key={props.key} cx={props.cx} cy={props.cy} r={3} fill={won ? '#22c55e' : '#ef4444'} stroke="none" />;
                  }}
                  activeDot={{ r: 6, fill: '#f0b429', stroke: '#060914', strokeWidth: 2 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Top Leagues */}
          <div className="chart-card" style={{ overflow: 'hidden' }}>
            <div className="chart-title">🏆 Top Championnats</div>
            <div className="chart-sub">Classés par rentabilité (ROI%)</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 220, overflowY: 'auto' }}>
              {league_stats.slice(0, 6).map((lg, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 10, border: '1px solid rgba(255,255,255,0.06)' }}>
                  <span style={{ fontSize: 18, flexShrink: 0 }}>{getLeagueFlag(lg.league)}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{lg.league.split('•').pop()?.trim()}</div>
                    <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>{lg.total} matchs · {lg.won}V {lg.lost}D</div>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 18, fontWeight: 800, color: '#f0b429' }}>{lg.win_rate}%</div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: lg.profit >= 0 ? '#22c55e' : '#ef4444' }}>ROI {lg.roi}%</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── LIVE SECTION ─────────────────────────── */}
        {liveMatches.length > 0 && (
          <div className="live-section">
            <div className="section-label">
              <span style={{ color: '#ef4444', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#ef4444', display: 'inline-block', animation: 'live-pulse 1.5s infinite' }} />
                MATCHS EN DIRECT ({liveMatches.length})
              </span>
            </div>
            <div className="live-cards">
              {liveMatches.map(m => <LiveCard key={m.id} m={m} />)}
            </div>
          </div>
        )}

        {/* ── TABS PANEL ───────────────────────────── */}
        <div className="panel-card">
          {/* Tab Nav */}
          <div className="tab-nav">
            <button className={`tab-btn ${tab === 'selected' ? 'active' : ''}`} onClick={() => setTab('selected')}>
              {Icon.Star}
              Matchs Retenus
              <span className="tab-count">{upcomingSelected.length}</span>
            </button>
            <button className={`tab-btn ${tab === 'rejected' ? 'active' : ''}`} onClick={() => setTab('rejected')}>
              {Icon.Ban}
              Rejetés
              <span className="tab-count">{upcomingRejected.length}</span>
            </button>
            <button className={`tab-btn ${tab === 'history' ? 'active' : ''}`} onClick={() => setTab('history')}>
              {Icon.History}
              Historique
              <span className="tab-count">{historyMatches.length}</span>
            </button>
            <button className={`tab-btn ${tab === 'leagues' ? 'active' : ''}`} onClick={() => setTab('leagues')}>
              {Icon.Award}
              Championnats
              <span className="tab-count">{league_stats.length}</span>
            </button>
          </div>

          {/* Search toolbar */}
          {tab !== 'leagues' && (
            <div className="table-toolbar">
              <div className="search-wrap">
                {Icon.Search}
                <input className="search-input" placeholder="Équipe, ligue…" value={search} onChange={e => setSearch(e.target.value)} />
              </div>
              <select className="filter-select" value={leagueFilter} onChange={e => setLeagueFilter(e.target.value)}>
                <option value="ALL">Toutes les ligues</option>
                {allLeagues.map((l, i) => <option key={i} value={l}>{l}</option>)}
              </select>
            </div>
          )}

          {/* ── TAB: MATCHS RETENUS ── */}
          {tab === 'selected' && (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date &amp; Heure</th>
                    <th>Rencontre</th>
                    <th>Championnat</th>
                    <th style={{ textAlign: 'center' }}>BTTS (Oui/Non)</th>
                    <th style={{ textAlign: 'center' }}>Over 2.5</th>
                    <th>Buteur Référence</th>
                    <th style={{ textAlign: 'center' }}>Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {filter(upcomingSelected).length === 0
                    ? <tr><td colSpan={7} className="empty-state">Aucun match retenu trouvé.</td></tr>
                    : filter(upcomingSelected).map(m => (
                      <tr key={m.id}>
                        <td style={{ color: '#64748b', fontSize: 12, whiteSpace: 'nowrap' }}>{m.date_str}</td>
                        <td>
                          <div className="match-name">{m.dom} <span style={{ color: '#475569', fontWeight: 400 }}>vs</span> {m.ext}</div>
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span>{getLeagueFlag(m.league)}</span>
                            <span className="match-league" style={{ color: '#64748b' }}>{m.league}</span>
                          </div>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <span className="cote-badge blue">{fmtCote(m.btts_oui)}{m.btts_non ? ` / ${fmtCote(m.btts_non)}` : ''}</span>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <span className="cote-badge green">{fmtCote(m.over25)}</span>
                        </td>
                        <td>
                          {m.buteur_name
                            ? <div className="buteur-cell">
                                <span className="buteur-name">{m.buteur_name}</span>
                                <span className="buteur-cote">@{m.buteur_cote}</span>
                              </div>
                            : <span style={{ color: '#334155', fontSize: 12 }}>—</span>
                          }
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <span className="status-badge pending">{Icon.Clock} À venir</span>
                        </td>
                      </tr>
                    ))
                  }
                </tbody>
              </table>
            </div>
          )}

          {/* ── TAB: REJETÉS ── */}
          {tab === 'rejected' && (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Rencontre</th>
                    <th>Championnat</th>
                    <th style={{ textAlign: 'center' }}>BTTS (Oui/Non)</th>
                    <th style={{ textAlign: 'center' }}>Over 2.5</th>
                    <th>Raison du Rejet</th>
                  </tr>
                </thead>
                <tbody>
                  {filter(upcomingRejected).length === 0
                    ? <tr><td colSpan={6} className="empty-state">Aucun match rejeté trouvé.</td></tr>
                    : filter(upcomingRejected).map(m => (
                      <tr key={m.id}>
                        <td style={{ color: '#475569', fontSize: 12 }}>{m.date_str}</td>
                        <td>
                          <div style={{ fontWeight: 600, color: '#94a3b8', fontSize: 13 }}>{m.dom} vs {m.ext}</div>
                        </td>
                        <td>
                          <span style={{ fontSize: 11, color: '#475569' }}>{getLeagueFlag(m.league)} {m.league}</span>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <span className="cote-badge muted">{fmtCote(m.btts_oui)}{m.btts_non ? ` / ${fmtCote(m.btts_non)}` : ''}</span>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <span className="cote-badge muted">{fmtCote(m.over25)}</span>
                        </td>
                        <td>
                          <span className="reject-reason">{m.rejection_reason ?? '—'}</span>
                        </td>
                      </tr>
                    ))
                  }
                </tbody>
              </table>
            </div>
          )}

          {/* ── TAB: HISTORIQUE ── */}
          {tab === 'history' && (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Match</th>
                    <th>Championnat</th>
                    <th style={{ textAlign: 'center' }}>Score Final</th>
                    <th style={{ textAlign: 'center' }}>Over 2.5</th>
                    <th style={{ textAlign: 'center' }}>Résultat</th>
                    <th style={{ textAlign: 'right' }}>Profit (U)</th>
                  </tr>
                </thead>
                <tbody>
                  {filter(historyMatches).map(m => (
                    <tr key={m.id}>
                      <td style={{ color: '#475569', fontSize: 12, whiteSpace: 'nowrap' }}>{m.date_str}</td>
                      <td>
                        <div className="match-name">{m.dom} vs {m.ext}</div>
                      </td>
                      <td>
                        <span style={{ fontSize: 11, color: '#475569' }}>{getLeagueFlag(m.league)} {m.league}</span>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <span className="score-final">{m.score_dom} – {m.score_ext}</span>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <span className="cote-badge gold">{fmtCote(m.over25)}</span>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        {m.selection_status === 'WON'
                          ? <span className="status-badge won">{Icon.Check} GAGNÉ</span>
                          : <span className="status-badge lost">{Icon.X} PERDU</span>
                        }
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <span className={m.profit_units >= 0 ? 'profit-pos' : 'profit-neg'}>
                          {m.profit_units >= 0 ? `+${m.profit_units.toFixed(2)}` : m.profit_units.toFixed(2)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── TAB: CHAMPIONNATS ── */}
          {tab === 'leagues' && (
            <div className="league-grid">
              {league_stats.map((lg, i) => (
                <div key={i} className="league-row">
                  <span className="league-flag">{getLeagueFlag(lg.league)}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="league-name">{lg.league}</div>
                    <div className="league-meta">
                      {lg.total} matchs &nbsp;·&nbsp;
                      <span style={{ color: '#22c55e', fontWeight: 700 }}>{lg.won}V</span>
                      {' '}/{' '}
                      <span style={{ color: '#ef4444', fontWeight: 700 }}>{lg.lost}D</span>
                    </div>
                  </div>
                  <div className="league-stats">
                    <div className="league-wr">{lg.win_rate}%</div>
                    <div className={`league-roi ${lg.profit >= 0 ? 'profit-pos' : 'profit-neg'}`}>
                      ROI {lg.roi}% &nbsp;({lg.profit >= 0 ? `+${lg.profit}` : lg.profit} U)
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Update bar */}
          <div className="update-bar">
            <span>Dernière synchronisation Unibet : <strong style={{ color: '#94a3b8' }}>{lastUpdate}</strong></span>
            <span>{summary.total_scanned_upcoming} matchs scannés · {summary.total_selected_upcoming} retenus</span>
          </div>
        </div>
      </div>
    </>
  );
}
