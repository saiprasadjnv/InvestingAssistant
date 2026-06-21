/**
 * CompanyCard — Per-company summary tile with latest analysis info and job run status.
 */
import SentimentBadge from './SentimentBadge';

export default function CompanyCard({ company, onClick }) {
  const {
    ticker, name, sector,
    analysis_count = 0,
    latest_sentiment,
    latest_impact_score,
    source_breakdown = {},
    latest_run_status,
    latest_run_at,
  } = company;

  const runStatusColor = latest_run_status === 'COMPLETED' ? 'var(--positive)'
    : latest_run_status === 'FAILED' ? 'var(--negative)'
    : latest_run_status === 'RUNNING' ? '#818cf8'
    : 'var(--text-muted)';

  const runStatusBg = latest_run_status === 'COMPLETED' ? 'var(--positive-bg)'
    : latest_run_status === 'FAILED' ? 'var(--negative-bg)'
    : latest_run_status === 'RUNNING' ? 'rgba(99,102,241,0.15)'
    : 'var(--bg-input)';

  const runStatusBorder = latest_run_status === 'COMPLETED' ? 'var(--positive-border)'
    : latest_run_status === 'FAILED' ? 'var(--negative-border)'
    : latest_run_status === 'RUNNING' ? 'rgba(99,102,241,0.3)'
    : 'var(--border-subtle)';

  const formatRunTime = (isoStr) => {
    if (!isoStr) return '';
    try {
      return new Date(isoStr).toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      });
    } catch { return ''; }
  };

  return (
    <div className="card company-card animate-in" onClick={() => onClick?.(ticker)}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div className="company-card__ticker">{ticker}</div>
          <div className="company-card__name">{name}</div>
          <span className="company-card__sector">{sector}</span>
        </div>
        {latest_sentiment && (
          <SentimentBadge sentiment={latest_sentiment} />
        )}
      </div>

      <div className="company-card__stats">
        <div className="company-card__stat">
          <div className="company-card__stat-value" style={{ color: 'var(--accent-blue)' }}>
            {analysis_count}
          </div>
          <div className="company-card__stat-label">Analyses</div>
        </div>
        <div className="company-card__stat">
          <div className="company-card__stat-value" style={{
            color: latest_impact_score >= 0.7 ? 'var(--positive)' :
                   latest_impact_score >= 0.4 ? 'var(--neutral)' : 'var(--text-muted)'
          }}>
            {latest_impact_score != null ? (latest_impact_score * 100).toFixed(0) + '%' : '—'}
          </div>
          <div className="company-card__stat-label">Impact</div>
        </div>
        <div className="company-card__stat">
          <div className="company-card__stat-value" style={{ color: 'var(--accent-teal)' }}>
            {Object.keys(source_breakdown).length || (analysis_count > 0 ? '✓' : '—')}
          </div>
          <div className="company-card__stat-label">Sources</div>
        </div>
      </div>

      {/* Latest job run status */}
      {latest_run_status && (
        <div style={{
          marginTop: '10px',
          paddingTop: '10px',
          borderTop: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {latest_run_status === 'RUNNING' && (
              <span style={{
                width: '6px', height: '6px', borderRadius: '50%',
                background: '#818cf8',
                animation: 'pulse 1.5s ease-in-out infinite',
                flexShrink: 0,
              }} />
            )}
            <span className="pill" style={{
              background: runStatusBg,
              color: runStatusColor,
              border: `1px solid ${runStatusBorder}`,
              fontSize: '0.688rem',
              padding: '2px 8px',
            }}>
              {latest_run_status}
            </span>
          </div>
          {latest_run_at && (
            <span style={{
              color: 'var(--text-muted)',
              fontSize: '0.688rem',
            }}>
              {formatRunTime(latest_run_at)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
