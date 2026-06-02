/**
 * CompanyCard — Per-company summary tile with latest analysis info.
 */
import SentimentBadge from './SentimentBadge';

export default function CompanyCard({ company, onClick }) {
  const {
    ticker, name, sector,
    analysis_count = 0,
    latest_sentiment,
    latest_impact_score,
    source_breakdown = {},
  } = company;

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
            {Object.keys(source_breakdown).length}
          </div>
          <div className="company-card__stat-label">Sources</div>
        </div>
      </div>
    </div>
  );
}
