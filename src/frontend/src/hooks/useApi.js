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

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${API_BASE}${endpoint}`);
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
      const id = setInterval(fetchData, refreshInterval);
      return () => clearInterval(id);
    }
  }, [fetchData, refreshInterval]);

  return { data, loading, error, refetch: fetchData };
}

/** Dashboard summary */
export function useDashboardSummary() {
  return useApi('/dashboard/summary');
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

/** Job runs */
export function useJobRuns(limit = 20) {
  return useApi(`/job-runs?limit=${limit}`);
}
