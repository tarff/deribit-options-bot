import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { apiClient } from '../client';
import type { Trade, RegimeStats } from '../types';

export function useTradeStats() {
  const { tradeStats, setTradeStats } = useAppStore();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      const data = await apiClient.getTradeStats();
      setTradeStats(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch trade stats');
    } finally {
      setIsLoading(false);
    }
  }, [setTradeStats]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  return { tradeStats, isLoading, error, refetch: fetchStats };
}

export function useTrades(limit: number = 100) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = useCallback(async () => {
    try {
      const data = await apiClient.getTrades(limit);
      setTrades(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch trades');
    } finally {
      setIsLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    fetchTrades();
  }, [fetchTrades]);

  return { trades, isLoading, error, refetch: fetchTrades };
}

export function useRegimeStats(days: number = 30) {
  const [regimeStats, setRegimeStats] = useState<RegimeStats[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      const data = await apiClient.getRegimeStats(days);
      setRegimeStats(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch regime stats');
    } finally {
      setIsLoading(false);
    }
  }, [days]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  return { regimeStats, isLoading, error, refetch: fetchStats };
}
