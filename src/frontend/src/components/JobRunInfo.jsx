/**
 * JobRunInfo — Pipeline execution history with expandable log viewer.
 * Used on the Dashboard. Click a row to expand and stream logs.
 */
import { useState, Fragment } from 'react';
import { useJobRunLogs, useCancelJob } from '../hooks/useApi';

export default function JobRunInfo({ runs = [] }) {
  const [expandedRunId, setExpandedRunId] = useState(null);
  const { data: logData } = useJobRunLogs(expandedRunId);
  const logEntries = logData?.entries || [];
  const { cancelJob } = useCancelJob();

  if (!runs.length) {
    return (
      <div className="card">
        <div className="card__header">
          <span className="card__title">⚡ Pipeline Runs</span>
        </div>
        <div className="empty-state">
          <div className="empty-state__icon">🔄</div>
          <p>No pipeline runs recorded yet</p>
        </div>
      </div>
    );
  }

  // Aggregate stats
  const totalCost = runs.reduce((s, r) => s + (r.total_cost_usd || 0), 0);
  const totalTokensIn = runs.reduce((s, r) => s + (r.total_tokens_in || 0), 0);
  const totalTokensOut = runs.reduce((s, r) => s + (r.total_tokens_out || 0), 0);

  const toggleExpand = (runId) => {
    setExpandedRunId(expandedRunId === runId ? null : runId);
  };

  return (
    <div className="card" style={{ gridColumn: '1 / -1' }}>
      <div className="card__header">
        <span className="card__title">⚡ Pipeline Execution History</span>
        <div style={{ display: 'flex', gap: 16 }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--accent-teal)' }}>
            💰 Total Cost: ${totalCost.toFixed(4)}
          </span>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            📊 {(totalTokensIn / 1000).toFixed(0)}k in / {(totalTokensOut / 1000).toFixed(0)}k out tokens
          </span>
        </div>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Run ID</th>
            <th>Status</th>
            <th>Started</th>
            <th>Companies</th>
            <th>Documents</th>
            <th>Analyses</th>
            <th>Tokens (in/out)</th>
            <th>Cost</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run, i) => (
            <Fragment key={run.run_id || i}>
              <tr
                className="animate-in"
                style={{ cursor: 'pointer', transition: 'background 0.15s' }}
                onClick={() => toggleExpand(run.run_id)}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-hover)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = ''; }}
              >
                <td className="mono" style={{ color: 'var(--accent-blue)', fontSize: '0.75rem' }}>
                  <span style={{ marginRight: '4px', fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                    {expandedRunId === run.run_id ? '▼' : '▶'}
                  </span>
                  {(run.run_id || '').slice(0, 12)}…
                </td>
                <td>
                  <span className={`pill ${
                    run.status === 'COMPLETED' ? 'sentiment-badge--positive' :
                    run.status === 'FAILED' ? 'sentiment-badge--negative' :
                    run.status === 'RUNNING' ? 'sentiment-badge--neutral' :
                    'sentiment-badge--neutral'
                  }`} style={run.status === 'RUNNING' ? { display: 'inline-flex', alignItems: 'center', gap: '4px' } : {}}>
                    {run.status === 'RUNNING' && (
                      <span style={{
                        width: '5px', height: '5px', borderRadius: '50%',
                        background: 'currentColor',
                        animation: 'pulse 1.5s ease-in-out infinite',
                      }} />
                    )}
                    {run.status}
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
                <td style={{ fontSize: '0.813rem', color: 'var(--text-secondary)' }}>
                  {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
                </td>
                <td className="mono">{run.companies_processed || 0}</td>
                <td className="mono">{run.documents_scraped || 0}</td>
                <td className="mono">{run.analyses_completed || 0}</td>
                <td className="mono" style={{ fontSize: '0.75rem' }}>
                  {((run.total_tokens_in || 0) / 1000).toFixed(1)}k / {((run.total_tokens_out || 0) / 1000).toFixed(1)}k
                </td>
                <td className="mono" style={{ color: 'var(--accent-teal)' }}>
                  ${(run.total_cost_usd || 0).toFixed(4)}
                </td>
                <td className="mono" style={{ color: (run.errors?.length || 0) > 0 ? 'var(--negative)' : 'var(--text-muted)' }}>
                  {run.errors?.length || 0}
                </td>
              </tr>

              {/* Expandable log viewer */}
              {expandedRunId === run.run_id && (
                <tr>
                  <td colSpan={9} style={{ padding: 0 }}>
                    <div style={{
                      background: 'var(--bg-primary)',
                      borderTop: '1px solid var(--border-subtle)',
                      maxHeight: '400px',
                      overflow: 'auto',
                      padding: 'var(--space-md)',
                    }}
                    ref={el => {
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
                                {entry.details?.traceback && (
                                  <details style={{ marginTop: '4px' }}>
                                    <summary style={{ cursor: 'pointer', fontSize: '0.688rem', color: 'var(--negative)' }}>
                                      Stack trace
                                    </summary>
                                    <pre style={{
                                      margin: '4px 0', padding: '8px',
                                      background: 'rgba(0,0,0,0.3)', borderRadius: '4px',
                                      fontSize: '0.688rem', whiteSpace: 'pre-wrap', overflowX: 'auto',
                                    }}>
                                      {entry.details.traceback}
                                    </pre>
                                  </details>
                                )}
                              </span>
                            </div>
                          ))}
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

      {/* LLM Provider Breakdown */}
      {runs.length > 0 && runs[0].calls_by_provider && (
        <div style={{ marginTop: 'var(--space-lg)', paddingTop: 'var(--space-lg)', borderTop: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '0.813rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-sm)' }}>
            LLM Provider Usage (Latest Run)
          </div>
          <div style={{ display: 'flex', gap: 16 }}>
            {Object.entries(runs[0].calls_by_provider || {}).map(([provider, count]) => (
              <div key={provider} className="pill" style={{
                background: 'var(--accent-blue-glow)',
                color: 'var(--accent-blue)',
                border: '1px solid var(--border-accent)',
                padding: '6px 14px',
                fontSize: '0.813rem',
              }}>
                {provider}: {count} calls
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
