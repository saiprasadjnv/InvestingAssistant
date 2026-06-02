/**
 * TopFindings — Top 10 high-confidence findings across all companies.
 */
import SentimentBadge from './SentimentBadge';
import ConfidenceGauge from './ConfidenceGauge';

export default function TopFindings({ findings = [] }) {
  if (!findings.length) {
    return (
      <div className="card">
        <div className="card__header">
          <span className="card__title">Top Findings</span>
        </div>
        <div className="empty-state">
          <div className="empty-state__icon">📊</div>
          <p>No high-confidence findings yet</p>
          <p style={{ fontSize: '0.75rem', marginTop: 8 }}>
            Findings appear after the pipeline runs
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card__header">
        <span className="card__title">🎯 Top High-Confidence Findings</span>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {findings.length} findings
        </span>
      </div>
      <div className="findings-list">
        {findings.map((f, i) => (
          <div className={`finding-item animate-in animate-in-delay-${i % 4 + 1}`} key={f.result_id || i}>
            <span className="finding-item__rank">#{i + 1}</span>
            <div className="finding-item__content">
              <div>
                <span className="finding-item__ticker">{f.ticker}</span>
                <span className="finding-item__source">{f.source}</span>
                <SentimentBadge
                  sentiment={f.sentiment}
                  confidence={f.sentiment_confidence}
                />
              </div>
              <div className="finding-item__summary">{f.summary}</div>
            </div>
            <ConfidenceGauge score={f.impact_score} size={48} strokeWidth={3} />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', minWidth: 60, textAlign: 'right' }}>
              {f.impact_direction === 'UP' ? '📈' : f.impact_direction === 'DOWN' ? '📉' : '➡️'}
              {' '}{f.impact_direction}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
