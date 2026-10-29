import { useEffect, useCallback, useState } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { apiClient } from '../client';
import { wsManager, isAccountUpdate } from '../websocket';
import type { AccountInfo } from '../types';

export function useAccount() {
  const { account, setAccount } = useAppStore();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAccount = useCallback(async () => {
    try {
      const data = await apiClient.getAccount();
      setAccount(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch account');
    } finally {
      setIsLoading(false);
    }
  }, [setAccount]);

  useEffect(() => {
    fetchAccount();

    // Handle WebSocket updates
    const unsubMessage = wsManager.onMessage((update) => {
      if (isAccountUpdate(update)) {
        setAccount(update.data as AccountInfo);
      }
    });

    return () => {
      unsubMessage();
    };
  }, [fetchAccount, setAccount]);

  return { account, isLoading, error, refetch: fetchAccount };
}
