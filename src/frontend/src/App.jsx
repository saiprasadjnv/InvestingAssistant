/**
 * InvestingAssistant — Root application component.
 */
import { useState } from 'react';
import Dashboard from './components/Dashboard';
import './index.css';

const VIEWS = ['Dashboard', 'Companies', 'Job Runs'];

export default function App() {
  const [activeView, setActiveView] = useState('Dashboard');

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="app-header__logo">
          <div className="app-header__icon">📈</div>
          <div>
            <div className="app-header__title">InvestingAssistant</div>
            <div className="app-header__subtitle">AI-Powered Stock Intelligence</div>
          </div>
        </div>
        <nav className="app-header__nav">
          {VIEWS.map((view) => (
            <button
              key={view}
              className={`nav-btn ${activeView === view ? 'nav-btn--active' : ''}`}
              onClick={() => setActiveView(view)}
            >
              {view}
            </button>
          ))}
        </nav>
      </header>

      {/* Main Content */}
      <main>
        <Dashboard />
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
        InvestingAssistant v1.0 — Monitoring {10} companies across 5 data sources
        <br />
        Pipeline runs every 3 hours • Powered by Gemini Flash
      </footer>
    </div>
  );
}
