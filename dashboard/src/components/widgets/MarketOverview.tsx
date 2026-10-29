import { motion } from 'framer-motion';
import { MetricCard } from '../common/MetricCard';
import { RegimeBadge } from '../common/RegimeBadge';
import type { MarketData } from '../../api/types';

interface MarketOverviewProps {
  data: MarketData | null;
  isLoading?: boolean;
}

export function MarketOverview({ data, isLoading }: MarketOverviewProps) {
  if (isLoading || !data) {
    return <MarketOverviewSkeleton />;
  }

  // Support both new and legacy field names
  const price = data.price ?? data.btc_price ?? 0;
  const priceChange = data.price_change_24h ?? data.btc_change_24h ?? 0;
  const currency = data.currency ?? 'BTC';

  const priceTrend = priceChange >= 0 ? 'up' : 'down';
  const ivRvTrend = data.iv_rv_spread >= 0 ? 'up' : 'down';

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-4"
    >
      {/* Regime Badge */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-display font-semibold text-text-primary">
          Market Overview
        </h2>
        <RegimeBadge regime={data.regime} size="lg" />
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label={`${currency} Price`}
          value={`$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          trend={priceTrend}
          trendValue={`${Math.abs(priceChange).toFixed(2)}%`}
          variant="cyan"
        />
        <MetricCard
          label="DVOL"
          value={data.dvol.toFixed(1)}
          subValue="Deribit Volatility Index"
          variant={data.dvol >= 60 ? 'warning' : 'default'}
        />
        <MetricCard
          label="IV Rank"
          value={`${(data.iv_rank * 100).toFixed(0)}%`}
          subValue="252-day percentile"
          variant={data.iv_rank >= 0.7 ? 'profit' : data.iv_rank <= 0.3 ? 'loss' : 'default'}
        />
        <MetricCard
          label="IV-RV Spread"
          value={`${data.iv_rv_spread >= 0 ? '+' : ''}${data.iv_rv_spread.toFixed(1)}%`}
          trend={ivRvTrend}
          trendValue={data.iv_rv_spread >= 5 ? 'Overpriced' : data.iv_rv_spread <= -5 ? 'Underpriced' : 'Fair'}
          variant={data.iv_rv_spread >= 5 ? 'profit' : data.iv_rv_spread <= -5 ? 'cyan' : 'default'}
        />
      </div>

      {/* Secondary Metrics */}
      <div className="grid grid-cols-3 gap-4">
        <div className="card">
          <p className="text-xs text-text-muted font-display uppercase tracking-wider">
            Realized Vol (20d)
          </p>
          <p className="text-xl font-mono font-semibold tabular-nums text-text-primary mt-1">
            {data.realized_vol.toFixed(1)}%
          </p>
        </div>
        <div className="card">
          <p className="text-xs text-text-muted font-display uppercase tracking-wider">
            IV Percentile
          </p>
          <p className="text-xl font-mono font-semibold tabular-nums text-text-primary mt-1">
            {(data.iv_percentile * 100).toFixed(0)}%
          </p>
        </div>
        <div className="card">
          <p className="text-xs text-text-muted font-display uppercase tracking-wider">
            Last Updated
          </p>
          <p className="text-sm font-mono text-text-secondary mt-1">
            {new Date(data.timestamp).toLocaleTimeString()}
          </p>
        </div>
      </div>
    </motion.div>
  );
}

function MarketOverviewSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-8 bg-bg-card rounded w-48" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="card h-24" />
        ))}
      </div>
    </div>
  );
}

export default MarketOverview;
