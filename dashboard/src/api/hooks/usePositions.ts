import { useEffect, useCallback, useState } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { apiClient } from '../client';
import { wsManager, isPositionsUpdate, isGreeksUpdate } from '../websocket';
import type { Position, StrategyPosition, PortfolioGreeks } from '../types';

export function usePositions(_status: 'open' | 'closed' | 'all' = 'open') {
  const { positions, setPositions, setPortfolioGreeks } = useAppStore();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPositions = useCallback(async () => {
    try {
      const [posData, greeksData] = await Promise.all([
        apiClient.getLivePositions(),
        apiClient.getPortfolioGreeks(),
      ]);
      setPositions(posData);
      setPortfolioGreeks(greeksData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch positions');
    } finally {
      setIsLoading(false);
    }
  }, [setPositions, setPortfolioGreeks]);

  useEffect(() => {
    fetchPositions();

    // Handle WebSocket updates
    const unsubMessage = wsManager.onMessage((update) => {
      if (isPositionsUpdate(update)) {
        setPositions(update.data as Position[]);
      }
      if (isGreeksUpdate(update)) {
        setPortfolioGreeks(update.data as PortfolioGreeks);
      }
    });

    return () => {
      unsubMessage();
    };
  }, [fetchPositions, setPositions, setPortfolioGreeks]);

  return { positions, isLoading, error, refetch: fetchPositions };
}

export function useStrategyPositions(status: 'open' | 'closed' | 'all' = 'open') {
  const [strategyPositions, setStrategyPositions] = useState<StrategyPosition[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStrategyPositions = useCallback(async () => {
    try {
      const data = await apiClient.getStrategyPositions(status);
      setStrategyPositions(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch strategy positions');
    } finally {
      setIsLoading(false);
    }
  }, [status]);

  useEffect(() => {
    fetchStrategyPositions();
  }, [fetchStrategyPositions]);

  return { strategyPositions, isLoading, error, refetch: fetchStrategyPositions };
}

export function usePortfolioGreeks() {
  const { portfolioGreeks, setPortfolioGreeks } = useAppStore();
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchGreeks = async () => {
      try {
        const data = await apiClient.getPortfolioGreeks();
        setPortfolioGreeks(data);
      } catch (err) {
        console.error('Failed to fetch portfolio Greeks:', err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchGreeks();

    // WebSocket updates
    const unsub = wsManager.onMessage((update) => {
      if (isGreeksUpdate(update)) {
        setPortfolioGreeks(update.data as PortfolioGreeks);
      }
    });

    return () => unsub();
  }, [setPortfolioGreeks]);

  return { portfolioGreeks, isLoading };
}
