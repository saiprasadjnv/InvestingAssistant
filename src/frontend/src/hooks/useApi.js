/**
 * API hooks for fetching data from the InvestingAssistant backend.
 * Uses a configurable base URL and provides loading/error states.
 */

import { useState, useEffect, useCallback } from 'react';

// API base URL — configurable via environment
const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

/**
 * Generic fetch hook with loading, error, and refetch support.
 */
export function useApi(endpoint, options = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const { enabled = true, refreshInterval = null } = options;

  const fetchData = useCallback(async (isRefresh = false) => {
    if (!enabled) return;
    
    try {
      // Only show loading on initial fetch, not background refreshes
      if (!isRefresh) {
        setLoading(true);
      }
      setError(null);

      const token = localStorage.getItem('ia_token');
      const headers = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const res = await fetch(`${API_BASE}${endpoint}`, { headers });

      if (res.status === 401) {
        window.dispatchEvent(new Event('auth-expired'));
        throw new Error('Session expired — please log in again');
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      console.error(`API Error [${endpoint}]:`, err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [endpoint, enabled]);

  useEffect(() => {
    fetchData();

    if (refreshInterval) {
      const id = setInterval(() => fetchData(true), refreshInterval);
      return () => clearInterval(id);
    }
  }, [fetchData, refreshInterval]);

  return { data, loading, error, refetch: fetchData };
}

/** Dashboard summary — polls every 10s for run status updates */
export function useDashboardSummary() {
  return useApi('/dashboard/summary', { refreshInterval: 10000 });
}

/** Top findings */
export function useTopFindings(limit = 10) {
  return useApi(`/dashboard/top-findings?limit=${limit}`);
}

/** Company list */
export function useCompanies() {
  return useApi('/companies');
}

/** Company detail */
export function useCompanyDetail(ticker) {
  return useApi(`/companies/${ticker}`, { enabled: !!ticker });
}

/** Analysis results for a company */
export function useAnalysis(ticker, source = null, limit = 50) {
  const params = new URLSearchParams({ limit: limit.toString() });
  if (source) params.set('source', source);
  return useApi(`/analysis/${ticker}?${params}`, { enabled: !!ticker });
}

/** Analysis history for a company */
export function useAnalysisHistory(ticker, limit = 100) {
  return useApi(`/analysis/${ticker}/history?limit=${limit}`, { enabled: !!ticker });
}

/** Job runs — polls every 5s for status updates */
export function useJobRuns(limit = 20, ticker = null) {
  const params = new URLSearchParams({ limit: limit.toString() });
  if (ticker) params.set('ticker', ticker);
  return useApi(`/job-runs?${params.toString()}`, { refreshInterval: 5000 });
}

/** Job run logs — polls every 2s for streaming while expanded */
export function useJobRunLogs(runId) {
  return useApi(
    runId ? `/job-runs/${runId}/logs` : null,
    { enabled: !!runId, refreshInterval: runId ? 2000 : null },
  );
}

/** Add a new company */
export function useAddCompany() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const addCompany = async (companyData) => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem('ia_token');
      const res = await fetch(`${API_BASE}/companies`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(companyData),
      });
      if (res.status === 401) {
        window.dispatchEvent(new Event('auth-expired'));
        throw new Error('Session expired');
      }
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  return { addCompany, loading, error };
}

/** Delete a company */
export function useDeleteCompany() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const deleteCompany = async (ticker) => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem('ia_token');
      const res = await fetch(`${API_BASE}/companies/${ticker}`, {
        method: 'DELETE',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      });
      if (res.status === 401) {
        window.dispatchEvent(new Event('auth-expired'));
        throw new Error('Session expired');
      }
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  return { deleteCompany, loading, error };
}

/** Trigger pipeline run for all companies */
export function useRunPipeline() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const runAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const token = localStorage.getItem('ia_token');
      const res = await fetch(`${API_BASE}/pipeline/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
      });
      if (res.status === 401) {
        window.dispatchEvent(new Event('auth-expired'));
        throw new Error('Session expired');
      }
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setResult(data);
      return data;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const runSingle = useCallback(async (ticker) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const token = localStorage.getItem('ia_token');
      const res = await fetch(`${API_BASE}/pipeline/run/${ticker}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
      });
      if (res.status === 401) {
        window.dispatchEvent(new Event('auth-expired'));
        throw new Error('Session expired');
      }
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setResult(data);
      return data;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { runAll, runSingle, loading, error, result };
}
