import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../client';
import type { HistoricalData } from '../types';
import { format, subDays } from 'date-fns';
import type { UTCTimestamp } from 'lightweight-charts';

export function useHistoricalData(
  days: number = 7,
  resolution: string = '1h'
) {
  const [data, setData] = useState<HistoricalData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setIsLoading(true);
      const endDate = format(new Date(), 'yyyy-MM-dd');
      const startDate = format(subDays(new Date(), days), 'yyyy-MM-dd');

      const historicalData = await apiClient.getHistoricalData(
        startDate,
        endDate,
        resolution
      );
      setData(historicalData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch historical data');
    } finally {
      setIsLoading(false);
    }
  }, [days, resolution]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, isLoading, error, refetch: fetchData };
}

export function useBtcChartData(days: number = 7, resolution: string = '1h') {
  const { data, isLoading, error } = useHistoricalData(days, resolution);

  const priceData = data?.price ?? data?.btc ?? [];
  const chartData = priceData.map((item) => ({
    time: Math.floor(new Date(item.timestamp).getTime() / 1000) as UTCTimestamp,
    open: item.open,
    high: item.high,
    low: item.low,
    close: item.close,
    value: item.close, // For line chart
  }));

  return { chartData, isLoading, error };
}

export function useDvolChartData(days: number = 7) {
  const { data, isLoading, error } = useHistoricalData(days, '1h');

  const chartData = data?.dvol.map((item) => ({
    time: Math.floor(new Date(item.timestamp).getTime() / 1000) as UTCTimestamp,
    value: item.value,
  })) || [];

  return { chartData, isLoading, error };
}
