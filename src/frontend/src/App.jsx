/**
 * InvestingAssistant — Root application component.
 * Handles authentication gating and navigation between Dashboard, Companies,
 * Job Runs, and Company Detail views.
 */
import { useState, useEffect } from 'react';
import Dashboard from './components/Dashboard';
import CompaniesView from './components/CompaniesView';
import JobRunsView from './components/JobRunsView';
import CompanyDetail from './components/CompanyDetail';
import LoginPage from './components/LoginPage';
import { useAuth } from './hooks/useAuth';
import './index.css';

const VIEWS = ['Dashboard', 'Companies', 'Job Runs'];

export default function App() {
  const { user, isAuthenticated, login, loginWithGoogle, register, logout, loading: authLoading } = useAuth();
  const [activeView, setActiveView] = useState('Dashboard');
  const [selectedCompany, setSelectedCompany] = useState(null);

  // Listen for auth-expired events from useApi
  useEffect(() => {
    const handler = () => logout();
    window.addEventListener('auth-expired', handler);
    return () => window.removeEventListener('auth-expired', handler);
  }, [logout]);

  // Full-page loading spinner while checking existing session
  if (authLoading) {
    return (
      <div className="auth-loading-screen">
        <div className="spinner" style={{ width: 48, height: 48 }} />
        <p style={{ color: 'var(--text-muted)', marginTop: 'var(--space-md)', fontSize: '0.875rem' }}>
          Checking session…
        </p>
      </div>
    );
  }

  // Show login page if not authenticated
  if (!isAuthenticated) {
    return <LoginPage onLogin={login} onGoogleLogin={loginWithGoogle} onRegister={register} />;
  }

  const handleCompanySelect = (ticker) => {
    setSelectedCompany(ticker);
    setActiveView('CompanyDetail');
  };

  const handleBackFromDetail = () => {
    setSelectedCompany(null);
    setActiveView('Dashboard');
  };

  const handleNavClick = (view) => {
    setSelectedCompany(null);
    setActiveView(view);
  };

  const renderView = () => {
    if (activeView === 'CompanyDetail' && selectedCompany) {
      return <CompanyDetail ticker={selectedCompany} onBack={handleBackFromDetail} />;
    }

    switch (activeView) {
      case 'Companies':
        return <CompaniesView onSelectCompany={handleCompanySelect} />;
      case 'Job Runs':
        return <JobRunsView />;
      case 'Dashboard':
      default:
        return <Dashboard onSelectCompany={handleCompanySelect} />;
    }
  };

  const displayName = user?.username || user?.email || user?.name || 'User';

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="app-header__logo" style={{ cursor: 'pointer' }} onClick={() => handleNavClick('Dashboard')}>
          <div className="app-header__icon">📈</div>
          <div>
            <div className="app-header__title">InvestingAssistant</div>
            <div className="app-header__subtitle">AI-Powered Stock Intelligence</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
          <nav className="app-header__nav">
            {VIEWS.map((view) => (
              <button
                key={view}
                className={`nav-btn ${activeView === view ? 'nav-btn--active' : ''}`}
                onClick={() => handleNavClick(view)}
              >
                {view}
              </button>
            ))}
          </nav>
          <button className="logout-btn" onClick={logout} title="Sign out">
            <span className="logout-btn__user">{displayName}</span>
            <span className="logout-btn__divider" />
            <span className="logout-btn__text">Logout</span>
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main>
        {renderView()}
      </main>

      {/* Footer */}
      <footer style={{
        textAlign: 'center',
        padding: 'var(--space-xl) 0 var(--space-lg)',
        borderTop: '1px solid var(--border-subtle)',
        marginTop: 'var(--space-2xl)',
        fontSize: '0.75rem',
        color: 'var(--text-muted)',
      }}>
        InvestingAssistant v1.0 — Monitoring {11} companies across 5 data sources
        <br />
        Pipeline runs every 3 hours • Powered by Gemini Flash
      </footer>
    </div>
  );
}
