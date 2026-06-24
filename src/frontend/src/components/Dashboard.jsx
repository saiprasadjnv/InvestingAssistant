/**
 * Dashboard — Main dashboard view with stat cards, top findings, and company grid.
 */
import { useState } from 'react';
import { useDashboardSummary, useTopFindings, useAnalysis, useJobRuns, useRunPipeline } from '../hooks/useApi';
import TopFindings from './TopFindings';
import CompanyCard from './CompanyCard';
import FindingsList from './FindingsList';
import JobRunInfo from './JobRunInfo';

export default function Dashboard({ onSelectCompany, onNavigate }) {
  const { data: summary, loading: summaryLoading } = useDashboardSummary();
  const { data: topData } = useTopFindings(10);
  const { data: jobData } = useJobRuns(10);
  const { runAll, loading: pipelineLoading, error: pipelineError, result: pipelineResult } = useRunPipeline();
  const [selectedTicker, setSelectedTicker] = useState(null);
  const { data: analysisData } = useAnalysis(selectedTicker);

  const sentimentDist = summary?.sentiment_distribution || {};
  const totalSentiment = (sentimentDist.POSITIVE || 0) + (sentimentDist.NEGATIVE || 0) + (sentimentDist.NEUTRAL || 0);

  const handleCompanyClick = (ticker) => {
    if (onSelectCompany) {
      onSelectCompany(ticker);
    } else {
      setSelectedTicker(selectedTicker === ticker ? null : ticker);
    }
  };

  return (
    <>
      {/* Pipeline notification */}
      {pipelineResult && (
        <div style={{
          background: 'linear-gradient(135deg, rgba(5,150,105,0.15), rgba(16,185,129,0.1))',
          border: '1px solid rgba(16,185,129,0.3)',
          borderRadius: '8px',
          padding: '12px 16px',
          margin: '0 0 16px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          color: '#10b981',
          fontSize: '0.9rem',
        }}>
          ✓ {pipelineResult.message}
        </div>
      )}
      {pipelineError && (
        <div style={{
          background: 'linear-gradient(135deg, rgba(239,68,68,0.15), rgba(239,68,68,0.1))',
          border: '1px solid rgba(239,68,68,0.3)',
          borderRadius: '8px',
          padding: '12px 16px',
          margin: '0 0 16px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          color: '#ef4444',
          fontSize: '0.9rem',
        }}>
          ✗ {pipelineError}
        </div>
      )}

      {/* Stat Cards Header with Run Analysis button */}
      <section className="section">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--text-primary)' }}>Overview</h2>
          <button
            onClick={runAll}
            disabled={pipelineLoading}
            style={{
              background: pipelineLoading ? 'rgba(5,150,105,0.3)' : 'linear-gradient(135deg, #059669, #10b981)',
              color: 'white',
              border: 'none',
              padding: '10px 20px',
              borderRadius: '8px',
              cursor: pipelineLoading ? 'wait' : 'pointer',
              fontWeight: 600,
              fontSize: '0.9rem',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              transition: 'all 0.2s',
              opacity: pipelineLoading ? 0.7 : 1,
            }}
          >
            {pipelineLoading ? '⏳ Running...' : '▶ Run Analysis (All Companies)'}
          </button>
        </div>
        <div className="grid-4">
          <div className="card stat-card--blue animate-in animate-in-delay-1" onClick={() => document.getElementById('tracked-companies')?.scrollIntoView({ behavior: 'smooth' })} style={{ cursor: 'pointer' }}>
            <div className="card__header">
              <span className="card__title">Companies Tracked</span>
              <div className="stat-icon stat-icon--blue">🏢</div>
            </div>
            <div className="card__value" style={{ color: 'var(--accent-blue)' }}>
              {summaryLoading ? '—' : summary?.total_companies || 0}
            </div>
            <div className="card__label">Active monitoring</div>
          </div>

          <div className="card stat-card--purple animate-in animate-in-delay-2" onClick={() => document.getElementById('tracked-companies')?.scrollIntoView({ behavior: 'smooth' })} style={{ cursor: 'pointer' }}>
            <div className="card__header">
              <span className="card__title">Total Analyses</span>
              <div className="stat-icon stat-icon--purple">📊</div>
            </div>
            <div className="card__value" style={{ color: 'var(--accent-purple)' }}>
              {summaryLoading ? '—' : summary?.total_analyses || 0}
            </div>
            <div className="card__label">Across all sources</div>
          </div>

          <div className="card stat-card--green animate-in animate-in-delay-3">
            <div className="card__header">
              <span className="card__title">Sentiment</span>
              <div className="stat-icon stat-icon--green">💹</div>
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 'var(--space-sm)' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--positive)' }}>
                  {sentimentDist.POSITIVE || 0}
                </div>
                <div style={{ fontSize: '0.625rem', color: 'var(--text-muted)' }}>Positive</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--negative)' }}>
                  {sentimentDist.NEGATIVE || 0}
                </div>
                <div style={{ fontSize: '0.625rem', color: 'var(--text-muted)' }}>Negative</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--neutral)' }}>
                  {sentimentDist.NEUTRAL || 0}
                </div>
                <div style={{ fontSize: '0.625rem', color: 'var(--text-muted)' }}>Neutral</div>
              </div>
            </div>
            {totalSentiment > 0 && (
              <div style={{ marginTop: 8, height: 4, borderRadius: 2, display: 'flex', overflow: 'hidden', background: 'var(--bg-input)' }}>
                <div style={{ width: `${(sentimentDist.POSITIVE / totalSentiment) * 100}%`, background: 'var(--positive)' }} />
                <div style={{ width: `${(sentimentDist.NEUTRAL / totalSentiment) * 100}%`, background: 'var(--neutral)' }} />
                <div style={{ width: `${(sentimentDist.NEGATIVE / totalSentiment) * 100}%`, background: 'var(--negative)' }} />
              </div>
            )}
          </div>

          <div className="card stat-card--teal animate-in animate-in-delay-4">
            <div className="card__header">
              <span className="card__title">Avg Impact</span>
              <div className="stat-icon stat-icon--teal">⚡</div>
            </div>
            <div className="card__value" style={{ color: 'var(--accent-teal)' }}>
              {summaryLoading ? '—' : summary?.average_impact_score != null
                ? (summary.average_impact_score * 100).toFixed(1) + '%'
                : '0%'}
            </div>
            <div className="card__label">Confidence score</div>
          </div>
        </div>
      </section>

      {/* Top Findings */}
      <section className="section">
        <TopFindings findings={topData?.findings || []} />
      </section>

      {/* Company Grid */}
      <section className="section" id="tracked-companies">
        <div className="section__header">
          <h2 className="section__title">🏢 Tracked Companies</h2>
          <button
            onClick={() => onNavigate?.('Companies')}
            style={{
              background: 'linear-gradient(135deg, var(--accent-blue), var(--accent-purple, #7c5cfc))',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              padding: '8px 16px',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: 'pointer',
              transition: 'opacity 0.2s',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
            onMouseEnter={e => { e.currentTarget.style.opacity = '0.85'; }}
            onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
          >
            + Add Company
          </button>
        </div>
        <div className="grid-3">
          {(summary?.companies || []).map((c) => (
            <CompanyCard
              key={c.ticker}
              company={c}
              onClick={handleCompanyClick}
            />
          ))}
        </div>
      </section>

      {/* Company Detail (when clicked) */}
      {selectedTicker && (
        <section className="section animate-in" style={{ scrollMarginTop: 20 }}>
          <FindingsList
            results={analysisData?.results || []}
            ticker={selectedTicker}
          />
        </section>
      )}

      {/* Job Runs */}
      <section className="section">
        <JobRunInfo runs={jobData?.runs || []} />
      </section>
    </>
  );
}
