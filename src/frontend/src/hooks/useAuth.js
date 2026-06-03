/**
 * Authentication hook for InvestingAssistant.
 * Manages JWT token lifecycle, login (password & Google), logout, and session validation.
 */

import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';
const TOKEN_KEY = 'ia_token';

export function useAuth() {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);

  const isAuthenticated = !!token && !!user;

  // Persist token to localStorage and update state
  const saveSession = useCallback((newToken, newUser) => {
    localStorage.setItem(TOKEN_KEY, newToken);
    setToken(newToken);
    setUser(newUser);
  }, []);

  // Clear session
  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  }, []);

  // Validate an existing token by calling /api/auth/me
  const validateToken = useCallback(async (existingToken) => {
    try {
      const res = await fetch(`${API_BASE}/auth/me`, {
        headers: { Authorization: `Bearer ${existingToken}` },
      });
      if (!res.ok) throw new Error('Token invalid');
      const data = await res.json();
      saveSession(existingToken, data.user || data);
    } catch {
      localStorage.removeItem(TOKEN_KEY);
    } finally {
      setLoading(false);
    }
  }, [saveSession]);

  // On mount, check for existing token
  useEffect(() => {
    const existingToken = localStorage.getItem(TOKEN_KEY);
    if (existingToken) {
      validateToken(existingToken);
    } else {
      setLoading(false);
    }
  }, [validateToken]);

  // Password login
  const login = useCallback(async (username, password) => {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.message || `Login failed (${res.status})`);
    }

    const data = await res.json();
    saveSession(data.token || data.access_token, data.user || { username });
    return data;
  }, [saveSession]);

  // Google credential login
  const loginWithGoogle = useCallback(async (credential) => {
    const res = await fetch(`${API_BASE}/auth/google`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.message || `Google login failed (${res.status})`);
    }

    const data = await res.json();
    saveSession(data.token || data.access_token, data.user || { email: data.email });
    return data;
  }, [saveSession]);

  // Register (sign up) a new account
  const register = useCallback(async (username, password, email = '') => {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, email }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.message || `Registration failed (${res.status})`);
    }

    const data = await res.json();
    saveSession(data.token || data.access_token, data.user || { username });
    return data;
  }, [saveSession]);

  return { user, token, isAuthenticated, login, loginWithGoogle, register, logout, loading };
}
