import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { type ColumnDef } from '@tanstack/react-table';
import { format } from 'date-fns';
import { useTrades } from '../api/hooks/useTradeStats';
import { DataTable, PnlCell, SideCell, PriceCell } from '../components/common/DataTable';
import { useAppStore } from '../stores/useAppStore';
import { getValueDecimals } from '../api/types';
import type { Trade } from '../api/types';

export function TradeHistory() {
  const { trades, isLoading } = useTrades(200);
  const marketData = useAppStore((state) => state.marketData);
  const decimals = getValueDecimals(marketData?.is_linear);

  const columns = useMemo<ColumnDef<Trade, unknown>[]>(
    () => [
      {
        accessorKey: 'timestamp',
        header: 'Time',
        cell: ({ row }) => (
          <span className="text-text-secondary text-sm font-mono">
            {format(new Date(row.original.timestamp), 'yyyy-MM-dd HH:mm:ss')}
          </span>
        ),
      },
      {
        accessorKey: 'instrument_name',
        header: 'Instrument',
        cell: ({ row }) => (
          <span className="text-text-primary font-medium">
            {row.original.instrument_name}
          </span>
        ),
      },
      {
        accessorKey: 'side',
        header: 'Side',
        cell: ({ row }) => <SideCell side={row.original.side} />,
      },
      {
        accessorKey: 'quantity',
        header: 'Quantity',
        cell: ({ row }) => (
          <span className="text-text-primary tabular-nums">
            {row.original.quantity.toFixed(4)}
          </span>
        ),
      },
      {
        accessorKey: 'price',
        header: 'Price',
        cell: ({ row }) => <PriceCell value={row.original.price} decimals={decimals} />,
      },
      {
        accessorKey: 'fee',
        header: 'Fee',
        cell: ({ row }) => (
          <span className="text-text-muted tabular-nums">
            {row.original.fee.toFixed(decimals)}
          </span>
        ),
      },
      {
        accessorKey: 'pnl',
        header: 'P&L',
        cell: ({ row }) => (
          row.original.pnl !== undefined ? (
            <PnlCell value={row.original.pnl} decimals={decimals} />
          ) : (
            <span className="text-text-muted">—</span>
          )
        ),
      },
      {
        accessorKey: 'strategy_type',
        header: 'Strategy',
        cell: ({ row }) => (
          row.original.strategy_type ? (
            <span className="px-2 py-0.5 bg-accent-cyan/10 text-accent-cyan text-xs rounded uppercase">
              {row.original.strategy_type}
            </span>
          ) : (
            <span className="text-text-muted text-xs">Manual</span>
          )
        ),
      },
      {
        accessorKey: 'order_type',
        header: 'Order Type',
        cell: ({ row }) => (
          <span className="text-text-secondary text-xs uppercase">
            {row.original.order_type}
          </span>
        ),
      },
    ],
    [decimals]
  );

  // Calculate summary stats
  const stats = useMemo(() => {
    if (trades.length === 0) return null;

    const tradesWithPnl = trades.filter((t) => t.pnl !== undefined);
    const totalPnl = tradesWithPnl.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
    const totalFees = trades.reduce((sum, t) => sum + t.fee, 0);
    const winners = tradesWithPnl.filter((t) => (t.pnl ?? 0) > 0).length;
    const winRate = tradesWithPnl.length > 0 ? (winners / tradesWithPnl.length) * 100 : 0;

    return { totalPnl, totalFees, winRate, totalTrades: trades.length };
  }, [trades]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-display font-semibold text-text-primary">
          Trade History
        </h2>

        {/* Export Button */}
        <button
          onClick={() => exportTrades(trades)}
          className="px-4 py-2 bg-bg-card border border-border rounded-lg
                     text-text-secondary hover:text-text-primary hover:border-accent-cyan
                     transition-all text-sm font-display"
        >
          Export CSV
        </button>
      </div>

      {/* Summary Stats */}
      {stats && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="grid grid-cols-4 gap-4"
        >
          <div className="card">
            <p className="text-xs text-text-muted uppercase">Total Trades</p>
            <p className="text-xl font-mono font-semibold text-text-primary">
              {stats.totalTrades}
            </p>
          </div>
          <div className="card">
            <p className="text-xs text-text-muted uppercase">Total P&L</p>
            <p className={`text-xl font-mono font-semibold ${stats.totalPnl >= 0 ? 'text-profit' : 'text-loss'}`}>
              {stats.totalPnl >= 0 ? '+' : ''}{stats.totalPnl.toFixed(decimals)}
            </p>
          </div>
          <div className="card">
            <p className="text-xs text-text-muted uppercase">Win Rate</p>
            <p className="text-xl font-mono font-semibold text-text-primary">
              {stats.winRate.toFixed(1)}%
            </p>
          </div>
          <div className="card">
            <p className="text-xs text-text-muted uppercase">Total Fees</p>
            <p className="text-xl font-mono font-semibold text-warning">
              -{stats.totalFees.toFixed(decimals)}
            </p>
          </div>
        </motion.div>
      )}

      {/* Trade Table */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="card"
      >
        {isLoading ? (
          <div className="animate-pulse space-y-3">
            {[...Array(10)].map((_, i) => (
              <div key={i} className="h-12 bg-bg-secondary rounded" />
            ))}
          </div>
        ) : (
          <DataTable
            data={trades}
            columns={columns}
            emptyMessage="No trades found"
          />
        )}
      </motion.div>
    </div>
  );
}

function exportTrades(trades: Trade[]) {
  const headers = ['Time', 'Instrument', 'Side', 'Quantity', 'Price', 'Fee', 'P&L', 'Strategy', 'Order Type'];
  const rows = trades.map((t) => [
    t.timestamp,
    t.instrument_name,
    t.side,
    t.quantity,
    t.price,
    t.fee,
    t.pnl ?? '',
    t.strategy_type ?? '',
    t.order_type,
  ]);

  const csv = [headers, ...rows].map((row) => row.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `trades_${format(new Date(), 'yyyy-MM-dd')}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default TradeHistory;
