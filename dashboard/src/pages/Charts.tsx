import { useState } from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';
import { PriceChart } from '../components/charts/PriceChart';
import { DvolChart } from '../components/charts/DvolChart';
import { useBtcChartData, useDvolChartData } from '../api/hooks/useHistoricalData';
import { useMarketData } from '../stores/useAppStore';

type TimeRange = '1D' | '7D' | '30D' | '90D';
type ChartType = 'line' | 'candlestick';

const timeRanges: { value: TimeRange; label: string; days: number }[] = [
  { value: '1D', label: '1D', days: 1 },
  { value: '7D', label: '7D', days: 7 },
  { value: '30D', label: '30D', days: 30 },
  { value: '90D', label: '90D', days: 90 },
];

export function Charts() {
  const [timeRange, setTimeRange] = useState<TimeRange>('7D');
  const [chartType, setChartType] = useState<ChartType>('line');

  const days = timeRanges.find((r) => r.value === timeRange)?.days ?? 7;
  const { chartData: btcData, isLoading: btcLoading } = useBtcChartData(days);
  const { chartData: dvolData, isLoading: dvolLoading } = useDvolChartData(days);
  const marketData = useMarketData();
  const currency = marketData?.currency ?? 'BTC';

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-display font-semibold text-text-primary">
          Market Charts
        </h2>

        <div className="flex items-center gap-4">
          {/* Time Range Selector */}
          <div className="flex bg-bg-card rounded-lg p-1">
            {timeRanges.map((range) => (
              <button
                key={range.value}
                onClick={() => setTimeRange(range.value)}
                className={clsx(
                  'px-3 py-1.5 text-sm font-display rounded-md transition-all',
                  timeRange === range.value
                    ? 'bg-accent-cyan text-bg-primary'
                    : 'text-text-secondary hover:text-text-primary'
                )}
              >
                {range.label}
              </button>
            ))}
          </div>

          {/* Chart Type Toggle */}
          <div className="flex bg-bg-card rounded-lg p-1">
            <button
              onClick={() => setChartType('line')}
              className={clsx(
                'px-3 py-1.5 text-sm font-display rounded-md transition-all',
                chartType === 'line'
                  ? 'bg-accent-cyan text-bg-primary'
                  : 'text-text-secondary hover:text-text-primary'
              )}
            >
              Line
            </button>
            <button
              onClick={() => setChartType('candlestick')}
              className={clsx(
                'px-3 py-1.5 text-sm font-display rounded-md transition-all',
                chartType === 'candlestick'
                  ? 'bg-accent-cyan text-bg-primary'
                  : 'text-text-secondary hover:text-text-primary'
              )}
            >
              Candles
            </button>
          </div>
        </div>
      </div>

      {/* Price Chart */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        {btcLoading ? (
          <div className="card h-[400px] animate-pulse" />
        ) : (
          <PriceChart
            data={btcData}
            type={chartType}
            height={400}
            title={`${currency}/USD`}
          />
        )}
      </motion.div>

      {/* DVOL Chart */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        {dvolLoading ? (
          <div className="card h-[300px] animate-pulse" />
        ) : (
          <DvolChart data={dvolData} height={300} showThresholds />
        )}
      </motion.div>
    </div>
  );
}

export default Charts;
