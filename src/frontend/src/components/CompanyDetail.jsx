/**
 * CompanyDetail — Detailed company findings page organized by source.
 * Shows SEC filings, Company News, X discussions, and Reddit (future).
 */
import { useState, Fragment } from 'react';
import { useAnalysis, useCompanyDetail, useRunPipeline, useJobRuns, useJobRunLogs, useCancelJob } from '../hooks/useApi';
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

/* Helper: compute outlook aggregation for a time horizon */
function computeOutlook(results, horizon) {
  const now = Date.now();
  const msMap = { 'Today': 86400000, 'This Week': 604800000, 'This Month': 2592000000, 'This Year': 31536000000 };
  const cutoff = now - (msMap[horizon] || msMap['This Year']);
  const filtered = results.filter(r => r.created_at && new Date(r.created_at).getTime() >= cutoff);
  if (filtered.length === 0) return null;

  let positiveCount = 0, negativeCount = 0, neutralCount = 0, totalImpact = 0;
  const factorMap = {};

  filtered.forEach(r => {
    const s = (r.sentiment || '').toUpperCase();
    if (s === 'POSITIVE') positiveCount++;
    else if (s === 'NEGATIVE') negativeCount++;
    else neutralCount++;
    totalImpact += (r.impact_score || 0);
    (r.key_factors || []).forEach(f => { factorMap[f] = (factorMap[f] || 0) + 1; });
  });

  const topFactors = Object.entries(factorMap)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([f]) => f);

  const avgImpact = Math.round((totalImpact / filtered.length) * 10) / 10;
  const dominant = positiveCount >= negativeCount && positiveCount >= neutralCount
    ? 'POSITIVE' : negativeCount >= positiveCount && negativeCount >= neutralCount
    ? 'NEGATIVE' : 'MIXED';

  return { positiveCount, negativeCount, neutralCount, avgImpact, topFactors, totalCount: filtered.length, dominant };
}

export default function CompanyDetail({ ticker, onBack }) {
  const { data: companyData, loading: compLoading } = useCompanyDetail(ticker);
  const [activeSource, setActiveSource] = useState('ALL');
  const [outlookTab, setOutlookTab] = useState('This Month');
  const { data: analysisData, loading: analysisLoading } = useAnalysis(
    ticker,
    activeSource === 'ALL' ? null : activeSource
  );
  const { data: allAnalysisData } = useAnalysis(ticker, null, 200);
  const allResults = allAnalysisData?.results || [];
  const { runSingle, loading: pipelineLoading, error: pipelineError, result: pipelineResult } = useRunPipeline();
  const { data: jobData, loading: jobsLoading } = useJobRuns(10, ticker);
  const runs = jobData?.runs || [];
  const [expandedRunId, setExpandedRunId] = useState(null);
  const { data: logData } = useJobRunLogs(expandedRunId);
  const logEntries = logData?.entries || [];
  const { cancelJob } = useCancelJob();

  const results = analysisData?.results || [];
  const company = companyData || {};
  const outlook = computeOutlook(allResults, outlookTab);

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
            <button
              onClick={() => runSingle(ticker)}
              disabled={pipelineLoading}
              style={{
                background: pipelineLoading ? 'rgba(5,150,105,0.3)' : 'linear-gradient(135deg, #059669, #10b981)',
                color: 'white',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '8px',
                cursor: pipelineLoading ? 'wait' : 'pointer',
                fontWeight: 600,
                fontSize: '0.85rem',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                marginLeft: 'auto',
                transition: 'all 0.2s',
                opacity: pipelineLoading ? 0.7 : 1,
              }}
            >
              {pipelineLoading ? '⏳ Running...' : `▶ Run Analysis`}
            </button>
          </div>
          {pipelineResult && (
            <div style={{
              background: 'linear-gradient(135deg, rgba(5,150,105,0.15), rgba(16,185,129,0.1))',
              border: '1px solid rgba(16,185,129,0.3)',
              borderRadius: '6px',
              padding: '8px 12px',
              marginTop: '8px',
              color: '#10b981',
              fontSize: '0.85rem',
            }}>
              ✓ {pipelineResult.message}
            </div>
          )}
          {pipelineError && (
            <div style={{
              background: 'linear-gradient(135deg, rgba(239,68,68,0.15), rgba(239,68,68,0.1))',
              border: '1px solid rgba(239,68,68,0.3)',
              borderRadius: '6px',
              padding: '8px 12px',
              marginTop: '8px',
              color: '#ef4444',
              fontSize: '0.85rem',
            }}>
              ✗ {pipelineError}
            </div>
          )}
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

      {/* Overall Company Outlook */}
      <section style={{ marginBottom: 'var(--space-xl)' }}>
        <div className="card">
          <div className="card__header">
            <span className="card__title">🔮 Overall Company Outlook</span>
          </div>
          <div style={{ display: 'flex', gap: '4px', padding: '0 var(--space-lg)', marginBottom: 'var(--space-lg)' }}>
            {['Today', 'This Week', 'This Month', 'This Year'].map(tab => (
              <button key={tab} onClick={() => setOutlookTab(tab)} style={{
                padding: '8px 16px', borderRadius: '8px', border: 'none', cursor: 'pointer',
                fontWeight: 600, fontSize: '0.813rem', transition: 'all 0.2s',
                background: outlookTab === tab ? 'linear-gradient(135deg, #6366f1, #8b5cf6)' : 'var(--bg-input)',
                color: outlookTab === tab ? 'white' : 'var(--text-muted)',
              }}>
                {tab}
              </button>
            ))}
          </div>
          <div style={{ padding: '0 var(--space-lg) var(--space-lg)' }}>
            {!outlook ? (
              <div style={{
                textAlign: 'center', padding: 'var(--space-xl)', color: 'var(--text-muted)',
                fontSize: '0.875rem',
              }}>
                📭 No analysis data available for this period
              </div>
            ) : (
              <>
                {/* Sentiment distribution bar */}
                <div style={{ marginBottom: 'var(--space-lg)' }}>
                  <div style={{ fontSize: '0.688rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>
                    Sentiment Distribution
                  </div>
                  <div style={{ display: 'flex', height: '10px', borderRadius: '5px', overflow: 'hidden', background: 'var(--bg-input)' }}>
                    {outlook.positiveCount > 0 && (
                      <div style={{ width: `${(outlook.positiveCount / outlook.totalCount) * 100}%`, background: 'linear-gradient(90deg, #10b981, #34d399)', transition: 'width 0.5s ease' }} />
                    )}
                    {outlook.neutralCount > 0 && (
                      <div style={{ width: `${(outlook.neutralCount / outlook.totalCount) * 100}%`, background: 'linear-gradient(90deg, #6b7280, #9ca3af)', transition: 'width 0.5s ease' }} />
                    )}
                    {outlook.negativeCount > 0 && (
                      <div style={{ width: `${(outlook.negativeCount / outlook.totalCount) * 100}%`, background: 'linear-gradient(90deg, #ef4444, #f87171)', transition: 'width 0.5s ease' }} />
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--space-md)', marginTop: '6px', fontSize: '0.75rem' }}>
                    <span style={{ color: '#10b981' }}>● Positive: {outlook.positiveCount}</span>
                    <span style={{ color: '#9ca3af' }}>● Neutral: {outlook.neutralCount}</span>
                    <span style={{ color: '#ef4444' }}>● Negative: {outlook.negativeCount}</span>
                  </div>
                </div>

                {/* Impact score + Key factors row */}
                <div style={{ display: 'flex', gap: 'var(--space-xl)', alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 'var(--space-lg)' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
                    <div style={{ fontSize: '0.688rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Avg Impact</div>
                    <ConfidenceGauge score={outlook.avgImpact} size={56} strokeWidth={4} />
                  </div>
                  {outlook.topFactors.length > 0 && (
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '0.688rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>Top Key Factors</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {outlook.topFactors.map((f, i) => (
                          <span key={i} className="pill" style={{
                            background: 'linear-gradient(135deg, rgba(99,102,241,0.12), rgba(139,92,246,0.12))',
                            color: '#a78bfa',
                            border: '1px solid rgba(139,92,246,0.25)',
                            fontSize: '0.688rem',
                          }}>
                            {f}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Text summary */}
                <div style={{
                  background: 'linear-gradient(135deg, rgba(99,102,241,0.06), rgba(139,92,246,0.04))',
                  border: '1px solid rgba(99,102,241,0.15)',
                  borderRadius: '8px',
                  padding: 'var(--space-md)',
                  fontSize: '0.85rem',
                  lineHeight: 1.6,
                  color: 'var(--text-secondary)',
                }}>
                  Based on <strong style={{ color: 'var(--text-primary)' }}>{outlook.totalCount}</strong> analyses, sentiment is predominantly{' '}
                  <strong style={{ color: outlook.dominant === 'POSITIVE' ? '#10b981' : outlook.dominant === 'NEGATIVE' ? '#ef4444' : '#8b5cf6' }}>
                    {outlook.dominant}
                  </strong>{' '}
                  with an average impact score of <strong style={{ color: 'var(--text-primary)' }}>{outlook.avgImpact}</strong>.
                  {outlook.topFactors.length > 0 && <> Key factors include: {outlook.topFactors.join(', ')}.</>}
                </div>
              </>
            )}
          </div>
        </div>
      </section>

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
                    {allResults.filter(r => r.source === key).length}
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

      {/* Recent Analysis Runs */}
      <div style={{ marginTop: 'var(--space-xl)' }}>
        <div className="section__header">
          <h2 className="section__title">🔄 Recent Analysis Runs</h2>
        </div>
        {jobsLoading ? (
          <div className="loading-container">
            <div className="spinner" />
            <span style={{ color: 'var(--text-muted)' }}>Loading run history...</span>
          </div>
        ) : runs.length === 0 ? (
          <div className="card">
            <div className="empty-state">
              <div className="empty-state__icon">📋</div>
              <p>No analysis runs yet for {ticker}</p>
              <p style={{ fontSize: '0.813rem', marginTop: 'var(--space-sm)', color: 'var(--text-muted)' }}>
                Click "Run Analysis" above to start
              </p>
            </div>
          </div>
        ) : (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Completed</th>
                  <th style={{ textAlign: 'center' }}>Documents</th>
                  <th>Triggered By</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run, i) => (
                  <Fragment key={run.run_id || i}>
                  <tr className="animate-in" style={{
                    animationDelay: `${Math.min(i * 0.03, 0.3)}s`,
                    cursor: 'pointer',
                  }} onClick={() => setExpandedRunId(expandedRunId === run.run_id ? null : run.run_id)}>
                    <td>
                      <span className="mono" style={{ color: 'var(--accent-blue)', fontSize: '0.813rem' }}>
                        {run.run_id || '—'}
                      </span>
                    </td>
                    <td>
                      <span className="pill" style={{
                        background: run.status === 'COMPLETED'
                          ? 'var(--positive-bg)' : run.status === 'FAILED'
                          ? 'var(--negative-bg)' : 'var(--neutral-bg)',
                        color: run.status === 'COMPLETED'
                          ? 'var(--positive)' : run.status === 'FAILED'
                          ? 'var(--negative)' : 'var(--neutral)',
                        border: `1px solid ${run.status === 'COMPLETED'
                          ? 'var(--positive-border)' : run.status === 'FAILED'
                          ? 'var(--negative-border)' : 'var(--neutral-border)'}`,
                      }}>
                        {run.status || 'UNKNOWN'}
                      </span>
                      {run.status === 'RUNNING' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); cancelJob(run.run_id); }}
                          style={{
                            background: 'none',
                            border: '1px solid var(--negative)',
                            color: 'var(--negative)',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '0.7rem',
                            fontWeight: 600,
                            marginLeft: '6px',
                            transition: 'all 0.2s',
                          }}
                          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.15)'; }}
                          onMouseLeave={e => { e.currentTarget.style.background = 'none'; }}
                        >
                          ■ Stop
                        </button>
                      )}
                    </td>
                    <td style={{ fontSize: '0.813rem' }}>
                      {run.started_at
                        ? new Date(run.started_at).toLocaleString('en-US', {
                            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                          })
                        : '—'}
                    </td>
                    <td style={{ fontSize: '0.813rem' }}>
                      {run.completed_at
                        ? new Date(run.completed_at).toLocaleString('en-US', {
                            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                          })
                        : '—'}
                    </td>
                    <td className="mono" style={{ textAlign: 'center' }}>
                      {run.documents_scraped || 0}
                    </td>
                    <td style={{ fontSize: '0.813rem', color: 'var(--text-muted)' }}>
                      {run.triggered_by || 'scheduled'}
                    </td>
                  </tr>
                  {expandedRunId === run.run_id && (
                    <tr>
                      <td colSpan={6} style={{ padding: 0 }}>
                        <div style={{
                          background: 'var(--bg-primary)',
                          borderTop: '1px solid var(--border-subtle)',
                          maxHeight: '400px',
                          overflow: 'auto',
                          padding: 'var(--space-md)',
                        }}
                        ref={el => {
                          // Auto-scroll to bottom when new entries arrive
                          if (el && run.status === 'RUNNING') {
                            el.scrollTop = el.scrollHeight;
                          }
                        }}>
                          {/* Streaming indicator */}
                          {run.status === 'RUNNING' && (
                            <div style={{
                              display: 'flex', alignItems: 'center', gap: '6px',
                              padding: '4px 8px', marginBottom: '8px',
                              background: 'rgba(99,102,241,0.1)',
                              border: '1px solid rgba(99,102,241,0.2)',
                              borderRadius: '4px',
                              fontSize: '0.75rem', color: '#818cf8',
                            }}>
                              <span style={{
                                width: '6px', height: '6px', borderRadius: '50%',
                                background: '#818cf8',
                                animation: 'pulse 1.5s ease-in-out infinite',
                              }} />
                              Live — streaming logs every 2s
                            </div>
                          )}
                          {logEntries.length === 0 ? (
                            <div style={{ color: 'var(--text-muted)', fontSize: '0.813rem', textAlign: 'center', padding: 'var(--space-md)' }}>
                              {run.status === 'RUNNING' ? 'Waiting for logs...' : 'No logs available for this run'}
                            </div>
                          ) : (
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', lineHeight: 1.6 }}>
                              {logEntries.map((entry, j) => (
                                <div key={j} style={{
                                  display: 'flex',
                                  gap: '8px',
                                  padding: '2px 0',
                                  borderBottom: '1px solid var(--border-subtle)',
                                  color: entry.level === 'ERROR' ? 'var(--negative)'
                                       : entry.level === 'WARN' ? '#f59e0b'
                                       : entry.level === 'DEBUG' ? 'var(--text-muted)'
                                       : 'var(--text-secondary)',
                                }}>
                                  <span style={{ color: 'var(--text-muted)', minWidth: '75px', flexShrink: 0 }}>
                                    {new Date(entry.ts).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                  </span>
                                  <span style={{
                                    minWidth: '45px', flexShrink: 0, fontWeight: 600,
                                    color: entry.level === 'ERROR' ? 'var(--negative)'
                                         : entry.level === 'WARN' ? '#f59e0b'
                                         : entry.level === 'INFO' ? 'var(--accent-blue)'
                                         : 'var(--text-muted)',
                                  }}>
                                    {entry.level}
                                  </span>
                                  <span style={{
                                    minWidth: '100px', flexShrink: 0,
                                    color: 'var(--accent-purple)',
                                  }}>
                                    [{entry.stage}]
                                  </span>
                                  <span style={{ flex: 1 }}>
                                    {entry.msg}
                                    {entry.details && Object.keys(entry.details).length > 0 && !entry.details.traceback && (
                                      <span style={{ color: 'var(--text-muted)', marginLeft: '8px' }}>
                                        {Object.entries(entry.details).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ')}
                                      </span>
                                    )}
                                  </span>
                                </div>
                              ))}
                              {logEntries.some(e => e.details?.traceback) && (
                                <details style={{ marginTop: '8px' }}>
                                  <summary style={{ cursor: 'pointer', color: 'var(--negative)', fontSize: '0.75rem' }}>
                                    Show error tracebacks
                                  </summary>
                                  {logEntries.filter(e => e.details?.traceback).map((e, j) => (
                                    <pre key={j} style={{
                                      background: 'rgba(239,68,68,0.1)',
                                      border: '1px solid rgba(239,68,68,0.2)',
                                      borderRadius: '4px',
                                      padding: '8px',
                                      margin: '4px 0',
                                      whiteSpace: 'pre-wrap',
                                      fontSize: '0.688rem',
                                      color: 'var(--negative)',
                                    }}>
                                      {e.details.traceback}
                                    </pre>
                                  ))}
                                </details>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
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
        {(!r.summary || r.summary === 'LLM response could not be parsed.') ? (
          <div style={{
            background: 'linear-gradient(135deg, rgba(245,158,11,0.08), rgba(251,191,36,0.06))',
            border: '1px solid rgba(245,158,11,0.25)',
            borderRadius: '6px',
            padding: '8px 12px',
            fontSize: '0.788rem',
            color: '#d97706',
            lineHeight: 1.5,
          }}>
            ⚠️ Analysis incomplete — LLM response could not be parsed. Re-run the analysis with valid API keys.
          </div>
        ) : r.summary}
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
