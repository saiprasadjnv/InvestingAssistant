/**
 * JobRunsView — Pipeline execution history with stats and details.
 */
import { useState, Fragment } from 'react';
import { useJobRuns, useJobRunLogs } from '../hooks/useApi';

export default function JobRunsView() {
  const { data: jobData, loading } = useJobRuns(50);
  const runs = jobData?.runs || [];
  const [expandedRunId, setExpandedRunId] = useState(null);
  const { data: logData } = useJobRunLogs(expandedRunId);
  const logEntries = logData?.entries || [];

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner" />
        <span style={{ color: 'var(--text-muted)' }}>Loading job history...</span>
      </div>
    );
  }

  return (
    <section className="section animate-in">
      {/* Summary stats */}
      <div className="grid-3" style={{ marginBottom: 'var(--space-xl)' }}>
        <div className="card">
          <div className="card__header">
            <span className="card__title">Total Runs</span>
            <div className="stat-icon stat-icon--blue">🔄</div>
          </div>
          <div className="card__value" style={{ color: 'var(--accent-blue)' }}>
            {jobData?.count || 0}
          </div>
        </div>
        <div className="card">
          <div className="card__header">
            <span className="card__title">Total Cost</span>
            <div className="stat-icon stat-icon--purple">💰</div>
          </div>
          <div className="card__value" style={{ color: 'var(--accent-purple)' }}>
            ${(jobData?.aggregate_cost_usd || 0).toFixed(4)}
          </div>
          <div className="card__label">API costs</div>
        </div>
        <div className="card">
          <div className="card__header">
            <span className="card__title">Total Tokens</span>
            <div className="stat-icon stat-icon--teal">📝</div>
          </div>
          <div className="card__value" style={{ color: 'var(--accent-teal)', fontSize: '1.5rem' }}>
            {((jobData?.aggregate_tokens_in || 0) + (jobData?.aggregate_tokens_out || 0)).toLocaleString()}
          </div>
          <div className="card__label">
            In: {(jobData?.aggregate_tokens_in || 0).toLocaleString()} / Out: {(jobData?.aggregate_tokens_out || 0).toLocaleString()}
          </div>
        </div>
      </div>

      {/* Runs table */}
      <div className="section__header">
        <h2 className="section__title">🔄 Pipeline Execution History</h2>
      </div>

      {runs.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <div className="empty-state__icon">📋</div>
            <p>No pipeline runs recorded yet</p>
            <p style={{ fontSize: '0.813rem', marginTop: 'var(--space-sm)', color: 'var(--text-muted)' }}>
              Run <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-blue)' }}>
                python scripts/local_run.py
              </code> to start the pipeline
            </p>
          </div>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Trigger</th>
                <th>Status</th>
                <th>Started</th>
                <th style={{ textAlign: 'center' }}>Companies</th>
                <th style={{ textAlign: 'center' }}>Documents</th>
                <th style={{ textAlign: 'center' }}>Analyses</th>
                <th style={{ textAlign: 'right' }}>Cost</th>
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
                    <span className="mono" style={{ color: 'var(--accent-blue)' }}>
                      {run.run_id ? run.run_id.substring(0, 16) : '—'}
                    </span>
                  </td>
                  <td style={{ fontSize: '0.813rem' }}>
                    <span className="pill" style={{
                      background: run.trigger_type === 'manual' ? 'rgba(99,102,241,0.15)' : 'var(--bg-input)',
                      color: run.trigger_type === 'manual' ? '#818cf8' : 'var(--text-muted)',
                      border: `1px solid ${run.trigger_type === 'manual' ? 'rgba(99,102,241,0.3)' : 'var(--border-subtle)'}`,
                    }}>
                      {run.trigger_type === 'manual' ? '🖱️ Manual' : '⏰ Scheduled'}
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
                  </td>
                  <td style={{ fontSize: '0.813rem' }}>
                    {run.started_at
                      ? new Date(run.started_at).toLocaleString('en-US', {
                          month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                        })
                      : '—'}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    {run.tickers && run.tickers.length > 0 ? (
                      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', justifyContent: 'center' }}>
                        {run.tickers.slice(0, 3).map(t => (
                          <span key={t} className="pill" style={{
                            background: 'var(--bg-input)',
                            color: 'var(--accent-blue)',
                            border: '1px solid var(--border-subtle)',
                            fontSize: '0.625rem',
                          }}>{t}</span>
                        ))}
                        {run.tickers.length > 3 && (
                          <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)' }}>
                            +{run.tickers.length - 3}
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="mono">{run.companies_processed || 0}</span>
                    )}
                  </td>
                  <td className="mono" style={{ textAlign: 'center' }}>
                    {run.documents_scraped || 0}
                  </td>
                  <td className="mono" style={{ textAlign: 'center' }}>
                    {run.analyses_completed || 0}
                  </td>
                  <td className="mono" style={{ textAlign: 'right', color: 'var(--accent-teal)' }}>
                    ${(run.total_cost_usd || 0).toFixed(4)}
                  </td>
                </tr>
                {expandedRunId === run.run_id && (
                  <tr>
                    <td colSpan={8} style={{ padding: 0 }}>
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
    </section>
  );
}
