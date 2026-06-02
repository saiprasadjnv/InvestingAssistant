/**
 * CompaniesView — Full companies list with search, sector filtering, click-to-detail,
 * add company modal, and delete company support.
 */
import { useState, useMemo } from 'react';
import { useDashboardSummary, useAddCompany, useDeleteCompany } from '../hooks/useApi';
import SentimentBadge from './SentimentBadge';

/* ---- inline styles for the modal ---- */
const overlayStyle = {
  position: 'fixed',
  inset: 0,
  zIndex: 1000,
  background: 'rgba(0,0,0,0.6)',
  backdropFilter: 'blur(4px)',
  WebkitBackdropFilter: 'blur(4px)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
};

const modalStyle = {
  maxWidth: 500,
  width: '90%',
  background: 'var(--bg-card)',
  border: '1px solid var(--border-subtle)',
  borderRadius: 'var(--radius-lg, 16px)',
  padding: 'var(--space-xl, 32px)',
  position: 'relative',
};

const inputStyle = {
  width: '100%',
  padding: '0.625rem 0.875rem',
  background: 'var(--bg-input, #1a1f2e)',
  border: '1px solid var(--border-subtle)',
  borderRadius: 'var(--radius-md, 10px)',
  color: 'var(--text-primary)',
  fontSize: '0.875rem',
  outline: 'none',
  transition: 'border-color 0.2s',
  boxSizing: 'border-box',
};

const labelStyle = {
  display: 'block',
  color: 'var(--text-muted)',
  fontSize: '0.75rem',
  fontWeight: 600,
  marginBottom: 6,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
};

const btnPrimary = {
  background: 'linear-gradient(135deg, var(--accent-blue), var(--accent-purple, #7c5cfc))',
  color: '#fff',
  border: 'none',
  borderRadius: 'var(--radius-md, 10px)',
  padding: '0.625rem 1.25rem',
  fontWeight: 600,
  fontSize: '0.875rem',
  cursor: 'pointer',
  transition: 'opacity 0.2s',
};

const btnCancel = {
  background: 'transparent',
  color: 'var(--text-muted)',
  border: '1px solid var(--border-subtle)',
  borderRadius: 'var(--radius-md, 10px)',
  padding: '0.625rem 1.25rem',
  fontWeight: 500,
  fontSize: '0.875rem',
  cursor: 'pointer',
  transition: 'opacity 0.2s',
};

const deleteBtn = {
  background: 'transparent',
  border: 'none',
  cursor: 'pointer',
  fontSize: '1rem',
  padding: '4px 8px',
  borderRadius: 'var(--radius-sm, 6px)',
  transition: 'background 0.2s',
  lineHeight: 1,
};

/* ---- blank form state ---- */
const EMPTY_FORM = {
  name: '',
  ticker: '',
  sector: '',
  cik: '',
  investor_page_url: '',
  news_page_url: '',
};

export default function CompaniesView({ onSelectCompany }) {
  /* --- data --- */
  const [refreshKey, setRefreshKey] = useState(0);
  const { data: summary, loading, refetch } = useDashboardSummary();
  const { addCompany, loading: adding, error: addError } = useAddCompany();
  const { deleteCompany, loading: deleting } = useDeleteCompany();

  /* --- local UI state --- */
  const [search, setSearch] = useState('');
  const [sectorFilter, setSectorFilter] = useState('ALL');
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState(null);
  const [deletingTicker, setDeletingTicker] = useState(null);

  const companies = summary?.companies || [];

  const sectors = useMemo(() => {
    const s = new Set(companies.map(c => c.sector).filter(Boolean));
    return ['ALL', ...Array.from(s).sort()];
  }, [companies]);

  const filtered = useMemo(() => {
    return companies.filter(c => {
      const matchSearch = !search ||
        c.ticker.toLowerCase().includes(search.toLowerCase()) ||
        c.name.toLowerCase().includes(search.toLowerCase());
      const matchSector = sectorFilter === 'ALL' || c.sector === sectorFilter;
      return matchSearch && matchSector;
    });
  }, [companies, search, sectorFilter]);

  /* --- helpers --- */
  const triggerRefresh = () => {
    setRefreshKey(k => k + 1);
    refetch();
  };

  const handleFieldChange = (field) => (e) => {
    let value = e.target.value;
    if (field === 'ticker') value = value.toUpperCase();
    setForm(f => ({ ...f, [field]: value }));
  };

  const handleAddSubmit = async (e) => {
    e.preventDefault();
    setFormError(null);
    if (!form.name.trim() || !form.ticker.trim()) {
      setFormError('Name and Ticker are required.');
      return;
    }
    try {
      await addCompany({
        name: form.name.trim(),
        ticker: form.ticker.trim(),
        sector: form.sector.trim() || undefined,
        cik: form.cik.trim() || undefined,
        investor_page_url: form.investor_page_url.trim() || undefined,
        news_page_url: form.news_page_url.trim() || undefined,
      });
      setShowModal(false);
      setForm(EMPTY_FORM);
      triggerRefresh();
    } catch (err) {
      setFormError(err.message);
    }
  };

  const handleDelete = async (ticker, e) => {
    e.stopPropagation(); // don't trigger row click
    if (!window.confirm(`Delete company "${ticker}"? This cannot be undone.`)) return;
    try {
      setDeletingTicker(ticker);
      await deleteCompany(ticker);
      triggerRefresh();
    } catch (err) {
      alert(`Failed to delete ${ticker}: ${err.message}`);
    } finally {
      setDeletingTicker(null);
    }
  };

  /* --- render --- */
  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner" />
        <span style={{ color: 'var(--text-muted)' }}>Loading companies...</span>
      </div>
    );
  }

  return (
    <section className="section animate-in">
      <div className="section__header" style={{ flexWrap: 'wrap', gap: 'var(--space-md)' }}>
        <h2 className="section__title">🏢 Tracked Companies ({filtered.length})</h2>
        <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Search */}
          <input
            type="text"
            placeholder="Search ticker or name..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="companies-search"
          />
          {/* Sector filter */}
          <select
            value={sectorFilter}
            onChange={e => setSectorFilter(e.target.value)}
            className="companies-select"
          >
            {sectors.map(s => (
              <option key={s} value={s}>{s === 'ALL' ? 'All Sectors' : s}</option>
            ))}
          </select>
          {/* Add Company button */}
          <button
            id="add-company-btn"
            style={btnPrimary}
            onClick={() => { setShowModal(true); setFormError(null); }}
          >
            + Add Company
          </button>
        </div>
      </div>

      {/* Companies table */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Company</th>
              <th>Sector</th>
              <th style={{ textAlign: 'center' }}>Analyses</th>
              <th style={{ textAlign: 'center' }}>Sentiment</th>
              <th style={{ textAlign: 'center' }}>Impact</th>
              <th></th>
              <th style={{ width: 48 }}></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c, i) => (
              <tr
                key={c.ticker}
                className="companies-row animate-in"
                style={{
                  cursor: 'pointer',
                  animationDelay: `${Math.min(i * 0.03, 0.3)}s`,
                }}
                onClick={() => onSelectCompany?.(c.ticker)}
              >
                <td>
                  <span className="mono" style={{
                    color: 'var(--accent-blue)',
                    fontWeight: 700,
                    fontSize: '0.938rem',
                  }}>
                    {c.ticker}
                  </span>
                </td>
                <td style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                  {c.name}
                </td>
                <td>
                  <span className="pill" style={{
                    background: 'var(--bg-input)',
                    color: 'var(--text-muted)',
                    border: '1px solid var(--border-subtle)',
                  }}>
                    {c.sector}
                  </span>
                </td>
                <td style={{ textAlign: 'center' }}>
                  <span className="mono" style={{ color: 'var(--accent-purple)' }}>
                    {c.analysis_count || 0}
                  </span>
                </td>
                <td style={{ textAlign: 'center' }}>
                  {c.latest_sentiment ? (
                    <SentimentBadge sentiment={c.latest_sentiment} />
                  ) : (
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>—</span>
                  )}
                </td>
                <td style={{ textAlign: 'center' }}>
                  <span className="mono" style={{
                    color: c.latest_impact_score >= 0.7 ? 'var(--positive)' :
                           c.latest_impact_score >= 0.4 ? 'var(--neutral)' : 'var(--text-muted)',
                  }}>
                    {c.latest_impact_score != null
                      ? (c.latest_impact_score * 100).toFixed(0) + '%'
                      : '—'}
                  </span>
                </td>
                <td>
                  <span style={{
                    color: 'var(--accent-blue)',
                    fontSize: '0.75rem',
                    fontWeight: 500,
                  }}>
                    View →
                  </span>
                </td>
                <td style={{ textAlign: 'center' }}>
                  <button
                    title={`Delete ${c.ticker}`}
                    style={{
                      ...deleteBtn,
                      opacity: deletingTicker === c.ticker ? 0.4 : 1,
                      pointerEvents: deletingTicker === c.ticker ? 'none' : 'auto',
                    }}
                    disabled={deletingTicker === c.ticker}
                    onClick={(e) => handleDelete(c.ticker, e)}
                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,80,80,0.15)'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    🗑️
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="empty-state">
            <div className="empty-state__icon">🔍</div>
            <p>No companies match your search</p>
          </div>
        )}
      </div>

      {/* ---- Add Company Modal ---- */}
      {showModal && (
        <div style={overlayStyle} onClick={() => setShowModal(false)}>
          <div
            style={modalStyle}
            className="animate-in"
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{
              color: 'var(--text-primary)',
              margin: '0 0 var(--space-lg, 24px) 0',
              fontSize: '1.125rem',
            }}>
              Add New Company
            </h3>

            <form onSubmit={handleAddSubmit}>
              <div style={{ display: 'grid', gap: 'var(--space-md, 16px)' }}>
                {/* Name */}
                <div>
                  <label style={labelStyle}>Name *</label>
                  <input
                    style={inputStyle}
                    type="text"
                    placeholder="e.g. Apple Inc."
                    value={form.name}
                    onChange={handleFieldChange('name')}
                    onFocus={e => { e.target.style.borderColor = 'var(--accent-blue)'; }}
                    onBlur={e => { e.target.style.borderColor = 'var(--border-subtle)'; }}
                    required
                  />
                </div>
                {/* Ticker */}
                <div>
                  <label style={labelStyle}>Ticker *</label>
                  <input
                    style={{ ...inputStyle, textTransform: 'uppercase' }}
                    type="text"
                    placeholder="e.g. AAPL"
                    value={form.ticker}
                    onChange={handleFieldChange('ticker')}
                    onFocus={e => { e.target.style.borderColor = 'var(--accent-blue)'; }}
                    onBlur={e => { e.target.style.borderColor = 'var(--border-subtle)'; }}
                    required
                  />
                </div>
                {/* Sector */}
                <div>
                  <label style={labelStyle}>Sector</label>
                  <input
                    style={inputStyle}
                    type="text"
                    placeholder="e.g. Technology"
                    value={form.sector}
                    onChange={handleFieldChange('sector')}
                    onFocus={e => { e.target.style.borderColor = 'var(--accent-blue)'; }}
                    onBlur={e => { e.target.style.borderColor = 'var(--border-subtle)'; }}
                  />
                </div>
                {/* CIK */}
                <div>
                  <label style={labelStyle}>CIK</label>
                  <input
                    style={inputStyle}
                    type="text"
                    placeholder="e.g. 0000320193"
                    value={form.cik}
                    onChange={handleFieldChange('cik')}
                    onFocus={e => { e.target.style.borderColor = 'var(--accent-blue)'; }}
                    onBlur={e => { e.target.style.borderColor = 'var(--border-subtle)'; }}
                  />
                </div>
                {/* Investor Page URL */}
                <div>
                  <label style={labelStyle}>Investor Page URL</label>
                  <input
                    style={inputStyle}
                    type="url"
                    placeholder="https://..."
                    value={form.investor_page_url}
                    onChange={handleFieldChange('investor_page_url')}
                    onFocus={e => { e.target.style.borderColor = 'var(--accent-blue)'; }}
                    onBlur={e => { e.target.style.borderColor = 'var(--border-subtle)'; }}
                  />
                </div>
                {/* News Page URL */}
                <div>
                  <label style={labelStyle}>News Page URL</label>
                  <input
                    style={inputStyle}
                    type="url"
                    placeholder="https://..."
                    value={form.news_page_url}
                    onChange={handleFieldChange('news_page_url')}
                    onFocus={e => { e.target.style.borderColor = 'var(--accent-blue)'; }}
                    onBlur={e => { e.target.style.borderColor = 'var(--border-subtle)'; }}
                  />
                </div>
              </div>

              {/* Error display */}
              {(formError || addError) && (
                <div style={{
                  marginTop: 'var(--space-md, 16px)',
                  padding: '0.625rem 0.875rem',
                  background: 'rgba(255,80,80,0.1)',
                  border: '1px solid rgba(255,80,80,0.3)',
                  borderRadius: 'var(--radius-md, 10px)',
                  color: '#ff5050',
                  fontSize: '0.813rem',
                }}>
                  {formError || addError}
                </div>
              )}

              {/* Buttons */}
              <div style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: 'var(--space-sm, 12px)',
                marginTop: 'var(--space-lg, 24px)',
              }}>
                <button
                  type="button"
                  style={btnCancel}
                  onClick={() => { setShowModal(false); setForm(EMPTY_FORM); }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  style={{ ...btnPrimary, opacity: adding ? 0.6 : 1 }}
                  disabled={adding}
                >
                  {adding ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                      <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                      Adding…
                    </span>
                  ) : (
                    'Add Company'
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
