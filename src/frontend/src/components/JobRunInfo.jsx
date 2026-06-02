/**
 * JobRunInfo — Pipeline execution history with LLM cost breakdown.
 */
export default function JobRunInfo({ runs = [] }) {
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
            <tr key={run.run_id || i} className="animate-in">
              <td className="mono" style={{ color: 'var(--accent-blue)', fontSize: '0.75rem' }}>
                {(run.run_id || '').slice(0, 12)}…
              </td>
              <td>
                <span className={`pill ${
                  run.status === 'COMPLETED' ? 'sentiment-badge--positive' :
                  run.status === 'FAILED' ? 'sentiment-badge--negative' :
                  'sentiment-badge--neutral'
                }`}>
                  {run.status}
                </span>
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
