import { motion } from 'framer-motion';
import clsx from 'clsx';
import { MetricCard } from '../common/MetricCard';
import { useAppStore } from '../../stores/useAppStore';
import { getValueDecimals, getSettlementUnit } from '../../api/types';
import type { AccountInfo } from '../../api/types';

interface AccountSummaryProps {
  account: AccountInfo | null;
  isLoading?: boolean;
}

export function AccountSummary({ account, isLoading }: AccountSummaryProps) {
  const marketData = useAppStore((state) => state.marketData);
  const isLinear = marketData?.is_linear;
  const decimals = getValueDecimals(isLinear);
  const unit = getSettlementUnit(isLinear, marketData?.currency);
  const prefix = isLinear ? '$' : '';

  if (isLoading || !account) {
    return <AccountSummarySkeleton />;
  }

  const pnlVariant = account.unrealized_pnl >= 0 ? 'profit' : 'loss';
  const marginStatus = account.margin_usage_pct >= 80 ? 'danger' : account.margin_usage_pct >= 50 ? 'warning' : 'safe';

  const fmtValue = (v: number) => `${prefix}${v.toFixed(decimals)}`;
  const fmtPnl = (v: number) => `${v >= 0 ? '+' : ''}${prefix}${v.toFixed(decimals)}`;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-4"
    >
      <h2 className="text-lg font-display font-semibold text-text-primary">
        Account Summary
        <span className="text-xs text-text-muted ml-2 font-mono">({unit})</span>
      </h2>

      {/* Main Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Equity"
          value={fmtValue(account.equity)}
          variant="cyan"
        />
        <MetricCard
          label="Balance"
          value={fmtValue(account.balance)}
        />
        <MetricCard
          label="Unrealized P&L"
          value={fmtPnl(account.unrealized_pnl)}
          variant={pnlVariant}
        />
        <MetricCard
          label="Today's P&L"
          value={fmtPnl(account.realized_pnl_today)}
          variant={account.realized_pnl_today >= 0 ? 'profit' : 'loss'}
        />
      </div>

      {/* Margin Section */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm text-text-muted font-display uppercase tracking-wider">
            Margin Usage
          </p>
          <span
            className={clsx(
              'text-sm font-mono font-semibold',
              marginStatus === 'danger' && 'text-loss',
              marginStatus === 'warning' && 'text-warning',
              marginStatus === 'safe' && 'text-profit'
            )}
          >
            {account.margin_usage_pct.toFixed(1)}%
          </span>
        </div>

        {/* Progress Bar */}
        <div className="h-2 bg-bg-secondary rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(account.margin_usage_pct, 100)}%` }}
            transition={{ duration: 0.5 }}
            className={clsx(
              'h-full rounded-full',
              marginStatus === 'danger' && 'bg-loss',
              marginStatus === 'warning' && 'bg-warning',
              marginStatus === 'safe' && 'bg-profit'
            )}
          />
        </div>

        {/* Margin Details */}
        <div className="grid grid-cols-3 gap-4 mt-4">
          <div>
            <p className="text-xs text-text-muted">Initial Margin</p>
            <p className="font-mono text-sm text-text-primary">
              {fmtValue(account.initial_margin)}
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Maintenance Margin</p>
            <p className="font-mono text-sm text-text-primary">
              {fmtValue(account.maintenance_margin)}
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Available Funds</p>
            <p className="font-mono text-sm text-profit">
              {fmtValue(account.available_funds)}
            </p>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function AccountSummarySkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-8 bg-bg-card rounded w-48" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="card h-24" />
        ))}
      </div>
      <div className="card h-32" />
    </div>
  );
}

export default AccountSummary;
