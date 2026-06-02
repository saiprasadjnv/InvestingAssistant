/**
 * Dashboard — Main dashboard view with stat cards, top findings, and company grid.
 */
import { useState } from 'react';
import { useDashboardSummary, useTopFindings, useAnalysis, useJobRuns } from '../hooks/useApi';
import TopFindings from './TopFindings';
import CompanyCard from './CompanyCard';
import FindingsList from './FindingsList';
import JobRunInfo from './JobRunInfo';

export default function Dashboard() {
  const { data: summary, loading: summaryLoading } = useDashboardSummary();
  const { data: topData } = useTopFindings(10);
  const { data: jobData } = useJobRuns(10);
  const [selectedTicker, setSelectedTicker] = useState(null);
  const { data: analysisData } = useAnalysis(selectedTicker);

  const sentimentDist = summary?.sentiment_distribution || {};
  const totalSentiment = (sentimentDist.POSITIVE || 0) + (sentimentDist.NEGATIVE || 0) + (sentimentDist.NEUTRAL || 0);

  const handleCompanyClick = (ticker) => {
    setSelectedTicker(selectedTicker === ticker ? null : ticker);
  };

  return (
    <>
      {/* Stat Cards */}
      <section className="section">
        <div className="grid-4">
          <div className="card stat-card--blue animate-in animate-in-delay-1">
            <div className="card__header">
              <span className="card__title">Companies Tracked</span>
              <div className="stat-icon stat-icon--blue">🏢</div>
            </div>
            <div className="card__value" style={{ color: 'var(--accent-blue)' }}>
              {summaryLoading ? '—' : summary?.total_companies || 0}
            </div>
            <div className="card__label">Active monitoring</div>
          </div>

          <div className="card stat-card--purple animate-in animate-in-delay-2">
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
      <section className="section">
        <div className="section__header">
          <h2 className="section__title">🏢 Tracked Companies</h2>
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
