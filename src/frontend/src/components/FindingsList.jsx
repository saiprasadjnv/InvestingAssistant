/**
 * FindingsList — Filterable list of analysis findings for a company.
 */
import { useState } from 'react';
import SentimentBadge from './SentimentBadge';
import ConfidenceGauge from './ConfidenceGauge';

const SOURCE_TABS = ['ALL', 'SEC', 'INVESTOR_PAGE', 'NEWS_PAGE', 'REDDIT', 'X'];
const SOURCE_LABELS = {
  ALL: 'All',
  SEC: 'SEC Filings',
  INVESTOR_PAGE: 'Investor Page',
  NEWS_PAGE: 'Company News',
  REDDIT: 'Reddit',
  X: 'X / Twitter',
};

export default function FindingsList({ results = [], ticker }) {
  const [activeSource, setActiveSource] = useState('ALL');

  const filtered = activeSource === 'ALL'
    ? results
    : results.filter(r => r.source === activeSource);

  return (
    <div className="card" style={{ gridColumn: '1 / -1' }}>
      <div className="card__header">
        <span className="card__title">
          {ticker ? `📋 ${ticker} Analysis Results` : '📋 Analysis Results'}
        </span>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {filtered.length} of {results.length}
        </span>
      </div>

      {/* Source tabs */}
      <div className="tabs">
        {SOURCE_TABS.map(src => (
          <button
            key={src}
            className={`tab-btn ${activeSource === src ? 'tab-btn--active' : ''}`}
            onClick={() => setActiveSource(src)}
          >
            {SOURCE_LABELS[src]}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state__icon">🔍</div>
          <p>No findings for this filter</p>
        </div>
      ) : (
        <div className="findings-list">
          {filtered.map((r, i) => (
            <div className="finding-item animate-in" key={r.result_id || i}>
              <ConfidenceGauge score={r.impact_score} size={44} strokeWidth={3} />
              <div className="finding-item__content">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span className="finding-item__source">{SOURCE_LABELS[r.source] || r.source}</span>
                  <SentimentBadge sentiment={r.sentiment} confidence={r.sentiment_confidence} />
                  <span style={{ fontSize: '0.688rem', color: 'var(--text-muted)' }}>
                    {r.impact_direction === 'UP' ? '📈' : r.impact_direction === 'DOWN' ? '📉' : '➡️'}
                  </span>
                </div>
                <div className="finding-item__summary" style={{ whiteSpace: 'normal', marginTop: 6 }}>
                  {r.source_title && <strong style={{ color: 'var(--text-primary)' }}>{r.source_title}: </strong>}
                  {r.summary}
                </div>
                {r.key_factors && r.key_factors.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
                    {r.key_factors.slice(0, 4).map((f, j) => (
                      <span key={j} className="pill" style={{
                        background: 'var(--bg-input)',
                        color: 'var(--text-muted)',
                        border: '1px solid var(--border-subtle)'
                      }}>
                        {f}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div style={{ fontSize: '0.688rem', color: 'var(--text-muted)', minWidth: 80, textAlign: 'right' }}>
                {r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
