/**
 * LoginPage — Premium dark glassmorphism login page for InvestingAssistant.
 * Supports username/password and Google Sign-In.
 */

import { useState, useEffect, useRef } from 'react';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

/* ---------- Inline Google SVG ---------- */
function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59a14.5 14.5 0 0 1 0-9.18l-7.98-6.19a24.0 24.0 0 0 0 0 21.56l7.98-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
    </svg>
  );
}

/* ---------- Loading Spinner ---------- */
function Spinner({ size = 20 }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        border: '2px solid rgba(255,255,255,0.2)',
        borderTopColor: '#fff',
        borderRadius: '50%',
        animation: 'spin 0.7s linear infinite',
      }}
    />
  );
}

export default function LoginPage({ onLogin, onGoogleLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const googleBtnRef = useRef(null);

  /* ---------- Google Identity Services ---------- */
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;

    const initGoogle = () => {
      if (!window.google?.accounts) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleGoogleCredential,
        auto_select: false,
      });
      if (googleBtnRef.current) {
        window.google.accounts.id.renderButton(googleBtnRef.current, {
          theme: 'outline',
          size: 'large',
          width: '100%',
          type: 'standard',
          shape: 'rectangular',
          text: 'signin_with',
        });
      }
    };

    // Load GSI script if not already present
    if (!document.getElementById('gsi-script')) {
      const script = document.createElement('script');
      script.id = 'gsi-script';
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      script.defer = true;
      script.onload = initGoogle;
      document.head.appendChild(script);
    } else {
      initGoogle();
    }
  }, []);

  const handleGoogleCredential = async (response) => {
    setError('');
    setGoogleLoading(true);
    try {
      await onGoogleLogin(response.credential);
    } catch (err) {
      setError(err.message || 'Google sign-in failed');
    } finally {
      setGoogleLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('Please enter both username and password');
      return;
    }
    setError('');
    setLoading(true);
    try {
      await onLogin(username, password);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  /* ---------- Styles ---------- */
  const styles = {
    wrapper: {
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 'var(--space-lg)',
      position: 'relative',
    },
    card: {
      width: '100%',
      maxWidth: 420,
      background: 'var(--bg-card)',
      backdropFilter: 'blur(20px)',
      WebkitBackdropFilter: 'blur(20px)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-xl)',
      overflow: 'hidden',
      boxShadow: '0 8px 40px rgba(0,0,0,0.5), 0 0 60px rgba(79,140,255,0.06)',
      animation: 'loginFadeIn 0.6s ease-out both',
    },
    accentLine: {
      height: 3,
      background: 'linear-gradient(90deg, var(--accent-blue), var(--accent-purple), var(--accent-teal))',
    },
    body: {
      padding: '2.5rem 2rem 2rem',
    },
    logoArea: {
      textAlign: 'center',
      marginBottom: '2rem',
    },
    logoIcon: {
      width: 52,
      height: 52,
      background: 'var(--gradient-blue)',
      borderRadius: 'var(--radius-md)',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: '1.6rem',
      boxShadow: 'var(--shadow-glow)',
      marginBottom: 'var(--space-md)',
    },
    title: {
      fontSize: '1.5rem',
      fontWeight: 700,
      background: 'linear-gradient(135deg, var(--text-primary) 0%, var(--accent-blue) 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      backgroundClip: 'text',
    },
    subtitle: {
      fontSize: '0.813rem',
      color: 'var(--text-muted)',
      marginTop: 4,
    },
    form: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-md)',
    },
    inputGroup: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
    },
    label: {
      fontSize: '0.75rem',
      fontWeight: 600,
      color: 'var(--text-secondary)',
      textTransform: 'uppercase',
      letterSpacing: '0.06em',
    },
    input: {
      padding: 'var(--space-sm) var(--space-md)',
      fontSize: '0.875rem',
      color: 'var(--text-primary)',
      background: 'var(--bg-input)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-md)',
      fontFamily: 'var(--font-sans)',
      outline: 'none',
      transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
    },
    primaryBtn: {
      padding: '0.75rem',
      fontSize: '0.875rem',
      fontWeight: 600,
      color: '#fff',
      background: 'var(--gradient-blue)',
      border: 'none',
      borderRadius: 'var(--radius-md)',
      cursor: 'pointer',
      fontFamily: 'var(--font-sans)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
      transition: 'all 0.25s ease',
      boxShadow: '0 4px 16px rgba(79,140,255,0.3)',
      marginTop: 'var(--space-xs)',
    },
    divider: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-md)',
      margin: 'var(--space-lg) 0',
    },
    dividerLine: {
      flex: 1,
      height: 1,
      background: 'var(--border-subtle)',
    },
    dividerText: {
      fontSize: '0.75rem',
      color: 'var(--text-muted)',
      whiteSpace: 'nowrap',
    },
    googleBtn: {
      width: '100%',
      padding: '0.7rem',
      fontSize: '0.875rem',
      fontWeight: 600,
      color: '#1f2937',
      background: '#fff',
      border: '1px solid #dadce0',
      borderRadius: 'var(--radius-md)',
      cursor: 'pointer',
      fontFamily: 'var(--font-sans)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 10,
      transition: 'all 0.2s ease',
    },
    error: {
      fontSize: '0.813rem',
      color: 'var(--negative)',
      background: 'var(--negative-bg)',
      border: '1px solid var(--negative-border)',
      borderRadius: 'var(--radius-sm)',
      padding: 'var(--space-sm) var(--space-md)',
      textAlign: 'center',
    },
    googleContainer: {
      display: 'flex',
      justifyContent: 'center',
    },
  };

  return (
    <div style={styles.wrapper}>
      <div style={styles.card}>
        {/* Gradient accent line */}
        <div style={styles.accentLine} />

        <div style={styles.body}>
          {/* Logo / Title */}
          <div style={styles.logoArea}>
            <div style={styles.logoIcon}>📈</div>
            <div style={styles.title}>InvestingAssistant</div>
            <div style={styles.subtitle}>AI-Powered Stock Intelligence</div>
          </div>

          {/* Error message */}
          {error && <div style={styles.error}>{error}</div>}

          {/* Login form */}
          <form style={styles.form} onSubmit={handleSubmit}>
            <div style={styles.inputGroup}>
              <label style={styles.label} htmlFor="login-username">Username</label>
              <input
                id="login-username"
                type="text"
                placeholder="Enter your username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={loading}
                autoComplete="username"
                className="login-input"
                style={styles.input}
              />
            </div>

            <div style={styles.inputGroup}>
              <label style={styles.label} htmlFor="login-password">Password</label>
              <input
                id="login-password"
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
                autoComplete="current-password"
                className="login-input"
                style={styles.input}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                ...styles.primaryBtn,
                opacity: loading ? 0.7 : 1,
              }}
              onMouseEnter={(e) => {
                if (!loading) e.currentTarget.style.transform = 'translateY(-1px)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'translateY(0)';
              }}
            >
              {loading ? <Spinner /> : 'Sign In'}
            </button>
          </form>

          {/* Divider */}
          <div style={styles.divider}>
            <div style={styles.dividerLine} />
            <span style={styles.dividerText}>— or —</span>
            <div style={styles.dividerLine} />
          </div>

          {/* Google Sign-In */}
          {GOOGLE_CLIENT_ID ? (
            <div style={styles.googleContainer}>
              {googleLoading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-sm) 0' }}>
                  <Spinner size={24} />
                </div>
              ) : (
                <div ref={googleBtnRef} style={{ width: '100%' }} />
              )}
            </div>
          ) : (
            <button
              type="button"
              style={styles.googleBtn}
              disabled={googleLoading}
              onClick={() => {
                setError('Google Sign-In is not configured. Set VITE_GOOGLE_CLIENT_ID.');
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#f8f9fa';
                e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.15)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = '#fff';
                e.currentTarget.style.boxShadow = 'none';
              }}
            >
              <GoogleIcon />
              Sign in with Google
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
