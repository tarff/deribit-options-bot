import { useEffect, useCallback, useState } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { apiClient } from '../client';
import { wsManager, isMarketUpdate } from '../websocket';
import type { MarketData } from '../types';

export function useMarketData() {
  const { marketData, setMarketData, setConnected } = useAppStore();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMarketData = useCallback(async () => {
    try {
      const data = await apiClient.getMarketData();
      setMarketData(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch market data');
    } finally {
      setIsLoading(false);
    }
  }, [setMarketData]);

  useEffect(() => {
    // Initial fetch
    fetchMarketData();

    // WebSocket connection
    wsManager.connect();

    // Handle WebSocket messages
    const unsubMessage = wsManager.onMessage((update) => {
      if (isMarketUpdate(update)) {
        setMarketData(update.data as MarketData);
      }
    });

    // Handle connection state
    const unsubConnection = wsManager.onConnectionChange((connected) => {
      setConnected(connected);
      if (connected) {
        // Refresh data on reconnect
        fetchMarketData();
      }
    });

    return () => {
      unsubMessage();
      unsubConnection();
    };
  }, [fetchMarketData, setMarketData, setConnected]);

  return { marketData, isLoading, error, refetch: fetchMarketData };
}

export function useMarketDataPolling(intervalMs: number = 10000) {
  const { marketData, setMarketData } = useAppStore();
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const data = await apiClient.getMarketData();
        setMarketData(data);
      } catch (err) {
        console.error('Market data polling error:', err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, intervalMs);

    return () => clearInterval(interval);
  }, [intervalMs, setMarketData]);

  return { marketData, isLoading };
}
