/**
 * CompanyDetail — Detailed company findings page organized by source.
 * Shows SEC filings, Company News, X discussions, and Reddit (future).
 */
import { useState } from 'react';
import { useAnalysis, useCompanyDetail } from '../hooks/useApi';
import SentimentBadge from './SentimentBadge';
import ConfidenceGauge from './ConfidenceGauge';

const SOURCE_SECTIONS = [
  { key: 'ALL', label: 'All Sources', icon: '📊' },
  { key: 'SEC', label: 'SEC Filings', icon: '📄' },
  { key: 'NEWS_PAGE', label: 'Company News', icon: '📰' },
  { key: 'INVESTOR_PAGE', label: 'Investor Relations', icon: '🏛️' },
  { key: 'X', label: 'X / Twitter', icon: '🐦' },
  { key: 'REDDIT', label: 'Reddit (Coming Soon)', icon: '🤖', disabled: true },
];

const SOURCE_LABELS = {
  SEC: 'SEC Filing',
  INVESTOR_PAGE: 'Investor Relations',
  NEWS_PAGE: 'Company News',
  REDDIT: 'Reddit',
  X: 'X / Twitter',
};

export default function CompanyDetail({ ticker, onBack }) {
  const { data: companyData, loading: compLoading } = useCompanyDetail(ticker);
  const [activeSource, setActiveSource] = useState('ALL');
  const { data: analysisData, loading: analysisLoading } = useAnalysis(
    ticker,
    activeSource === 'ALL' ? null : activeSource
  );

  const results = analysisData?.results || [];
  const company = companyData || {};

  return (
    <div className="company-detail animate-in">
      {/* Back button + Company header */}
      <div className="company-detail__header">
        <button className="company-detail__back" onClick={onBack}>
          ← Back to Dashboard
        </button>
        <div className="company-detail__info">
          <div className="company-detail__title-row">
            <h1 className="company-detail__ticker">{ticker}</h1>
            {company.latest_sentiment && (
              <SentimentBadge sentiment={company.latest_sentiment} />
            )}
          </div>
          <div className="company-detail__name">{company.name || ticker}</div>
          <div className="company-detail__meta">
            <span className="pill" style={{
              background: 'var(--bg-input)',
              color: 'var(--text-muted)',
              border: '1px solid var(--border-subtle)',
            }}>
              {company.sector || 'Unknown'}
            </span>
            <span style={{ fontSize: '0.813rem', color: 'var(--text-muted)' }}>
              CIK: {company.cik || '—'}
            </span>
            <span style={{ fontSize: '0.813rem', color: 'var(--text-muted)' }}>
              {company.analysis_count || 0} analyses
            </span>
          </div>
        </div>
      </div>

      {/* Source filter sidebar + results */}
      <div className="company-detail__layout">
        {/* Source sidebar */}
        <aside className="company-detail__sidebar">
          <div className="card" style={{ padding: 'var(--space-sm)' }}>
            <div style={{
              fontSize: '0.688rem',
              fontWeight: 600,
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              padding: 'var(--space-sm) var(--space-md)',
              marginBottom: 'var(--space-xs)',
            }}>
              Filter by Source
            </div>
            {SOURCE_SECTIONS.map(({ key, label, icon, disabled }) => (
              <button
                key={key}
                className={`source-filter-btn ${activeSource === key ? 'source-filter-btn--active' : ''} ${disabled ? 'source-filter-btn--disabled' : ''}`}
                onClick={() => !disabled && setActiveSource(key)}
                disabled={disabled}
              >
                <span>{icon}</span>
                <span>{label}</span>
                {key !== 'ALL' && !disabled && (
                  <span className="source-filter-btn__count">
                    {(analysisData?.results || []).filter(
                      r => key === 'ALL' || r.source === key
                    ).length || 0}
                  </span>
                )}
              </button>
            ))}
          </div>
        </aside>

        {/* Results area */}
        <div className="company-detail__results">
          {analysisLoading ? (
            <div className="loading-container">
              <div className="spinner" />
              <span style={{ color: 'var(--text-muted)' }}>Loading findings...</span>
            </div>
          ) : results.length === 0 ? (
            <div className="card">
              <div className="empty-state">
                <div className="empty-state__icon">🔍</div>
                <p>No findings yet for {SOURCE_LABELS[activeSource] || 'this source'}</p>
                <p style={{ fontSize: '0.813rem', marginTop: 'var(--space-sm)' }}>
                  Run the pipeline to scrape and analyze data
                </p>
              </div>
            </div>
          ) : (
            <div className="findings-grid">
              {results.map((r, i) => (
                <FindingCard key={r.result_id || i} result={r} index={i} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function FindingCard({ result: r, index }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`finding-card animate-in ${expanded ? 'finding-card--expanded' : ''}`}
      style={{ animationDelay: `${Math.min(index * 0.03, 0.3)}s` }}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="finding-card__header">
        <div className="finding-card__source-row">
          <span className="finding-card__source-badge">
            {SOURCE_LABELS[r.source] || r.source}
          </span>
          <SentimentBadge sentiment={r.sentiment} confidence={r.sentiment_confidence} />
          <span className="finding-card__direction">
            {r.impact_direction === 'UP' ? '📈' : r.impact_direction === 'DOWN' ? '📉' : '➡️'}
          </span>
        </div>
        <ConfidenceGauge score={r.impact_score} size={40} strokeWidth={3} />
      </div>

      {/* Title */}
      <div className="finding-card__title">
        {r.source_title || `${r.source} Analysis`}
      </div>

      {/* Summary */}
      <div className={`finding-card__summary ${expanded ? '' : 'finding-card__summary--truncated'}`}>
        {r.summary || 'No summary available'}
      </div>

      {/* Key factors */}
      {r.key_factors && r.key_factors.length > 0 && (
        <div className="finding-card__factors">
          {r.key_factors.slice(0, expanded ? 10 : 3).map((f, j) => (
            <span key={j} className="pill" style={{
              background: 'var(--bg-input)',
              color: 'var(--text-muted)',
              border: '1px solid var(--border-subtle)',
              fontSize: '0.625rem',
            }}>
              {f}
            </span>
          ))}
          {!expanded && r.key_factors.length > 3 && (
            <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)' }}>
              +{r.key_factors.length - 3} more
            </span>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="finding-card__footer">
        <span>{r.created_at ? new Date(r.created_at).toLocaleDateString('en-US', {
          month: 'short', day: 'numeric', year: 'numeric'
        }) : ''}</span>
        {r.source_url && (
          <a
            href={r.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="finding-card__link"
            onClick={e => e.stopPropagation()}
          >
            View Source ↗
          </a>
        )}
        <span style={{ fontSize: '0.625rem' }}>
          {expanded ? 'Click to collapse' : 'Click to expand'}
        </span>
      </div>
    </div>
  );
}
