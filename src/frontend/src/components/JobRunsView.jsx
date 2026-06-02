/**
 * JobRunsView — Pipeline execution history with stats and details.
 */
import { useJobRuns } from '../hooks/useApi';

export default function JobRunsView() {
  const { data: jobData, loading } = useJobRuns(50);
  const runs = jobData?.runs || [];

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
                <tr key={run.run_id || i} className="animate-in" style={{
                  animationDelay: `${Math.min(i * 0.03, 0.3)}s`,
                }}>
                  <td>
                    <span className="mono" style={{ color: 'var(--accent-blue)' }}>
                      {run.run_id ? run.run_id.substring(0, 16) : '—'}
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
                  <td className="mono" style={{ textAlign: 'center' }}>
                    {run.companies_processed || 0}
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
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
