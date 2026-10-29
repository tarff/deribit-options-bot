import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';
import { type ColumnDef } from '@tanstack/react-table';
import { usePositions, useStrategyPositions } from '../api/hooks/usePositions';
import { DataTable, PnlCell, SideCell, PriceCell } from '../components/common/DataTable';
import type { Position, StrategyPosition } from '../api/types';

type ViewMode = 'positions' | 'strategies';
type StatusFilter = 'open' | 'closed' | 'all';

export function Positions() {
  const [viewMode, setViewMode] = useState<ViewMode>('positions');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('open');

  const { positions, isLoading: positionsLoading } = usePositions(statusFilter);
  const { strategyPositions, isLoading: strategiesLoading } = useStrategyPositions(statusFilter);

  const positionColumns = useMemo<ColumnDef<Position, unknown>[]>(
    () => [
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
        accessorKey: 'direction',
        header: 'Side',
        cell: ({ row }) => <SideCell side={row.original.direction} />,
      },
      {
        accessorKey: 'size',
        header: 'Size',
        cell: ({ row }) => (
          <span className="text-text-primary tabular-nums">
            {row.original.size.toFixed(4)}
          </span>
        ),
      },
      {
        accessorKey: 'average_price',
        header: 'Entry Price',
        cell: ({ row }) => <PriceCell value={row.original.average_price} />,
      },
      {
        accessorKey: 'mark_price',
        header: 'Mark Price',
        cell: ({ row }) => <PriceCell value={row.original.mark_price} />,
      },
      {
        accessorKey: 'unrealized_pnl',
        header: 'Unrealized P&L',
        cell: ({ row }) => <PnlCell value={row.original.unrealized_pnl} />,
      },
      {
        accessorKey: 'delta',
        header: 'Δ',
        cell: ({ row }) => (
          <span className="text-accent-cyan tabular-nums">
            {row.original.delta.toFixed(4)}
          </span>
        ),
      },
      {
        accessorKey: 'gamma',
        header: 'Γ',
        cell: ({ row }) => (
          <span className="text-purple-400 tabular-nums">
            {row.original.gamma.toFixed(6)}
          </span>
        ),
      },
      {
        accessorKey: 'theta',
        header: 'Θ',
        cell: ({ row }) => (
          <span className={clsx(
            'tabular-nums',
            row.original.theta >= 0 ? 'text-profit' : 'text-loss'
          )}>
            {row.original.theta.toFixed(4)}
          </span>
        ),
      },
      {
        accessorKey: 'vega',
        header: 'ν',
        cell: ({ row }) => (
          <span className="text-profit tabular-nums">
            {row.original.vega.toFixed(4)}
          </span>
        ),
      },
    ],
    []
  );

  const strategyColumns = useMemo<ColumnDef<StrategyPosition, unknown>[]>(
    () => [
      {
        accessorKey: 'strategy_id',
        header: 'Strategy ID',
        cell: ({ row }) => (
          <span className="text-text-primary font-mono text-sm">
            {row.original.strategy_id.slice(0, 8)}...
          </span>
        ),
      },
      {
        accessorKey: 'strategy_type',
        header: 'Type',
        cell: ({ row }) => (
          <span className="px-2 py-1 bg-accent-cyan/10 text-accent-cyan text-xs rounded uppercase">
            {row.original.strategy_type}
          </span>
        ),
      },
      {
        accessorKey: 'legs',
        header: 'Legs',
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {row.original.legs.length}
          </span>
        ),
      },
      {
        accessorKey: 'total_pnl',
        header: 'Total P&L',
        cell: ({ row }) => <PnlCell value={row.original.total_pnl} />,
      },
      {
        accessorKey: 'portfolio_delta',
        header: 'Net Δ',
        cell: ({ row }) => (
          <span className="text-accent-cyan tabular-nums">
            {row.original.portfolio_delta.toFixed(4)}
          </span>
        ),
      },
      {
        accessorKey: 'portfolio_theta',
        header: 'Net Θ',
        cell: ({ row }) => (
          <span className={clsx(
            'tabular-nums',
            row.original.portfolio_theta >= 0 ? 'text-profit' : 'text-loss'
          )}>
            {row.original.portfolio_theta.toFixed(4)}
          </span>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <span className={clsx(
            'px-2 py-0.5 text-xs rounded uppercase',
            row.original.status === 'open'
              ? 'bg-profit/15 text-profit'
              : 'bg-text-muted/15 text-text-muted'
          )}>
            {row.original.status}
          </span>
        ),
      },
      {
        accessorKey: 'opened_at',
        header: 'Opened',
        cell: ({ row }) => (
          <span className="text-text-secondary text-sm font-mono">
            {new Date(row.original.opened_at).toLocaleDateString()}
          </span>
        ),
      },
    ],
    []
  );

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-display font-semibold text-text-primary">
          {viewMode === 'positions' ? 'Positions' : 'Strategy Positions'}
        </h2>

        <div className="flex items-center gap-4">
          {/* View Mode Toggle */}
          <div className="flex bg-bg-card rounded-lg p-1">
            <button
              onClick={() => setViewMode('positions')}
              className={clsx(
                'px-3 py-1.5 text-sm font-display rounded-md transition-all',
                viewMode === 'positions'
                  ? 'bg-accent-cyan text-bg-primary'
                  : 'text-text-secondary hover:text-text-primary'
              )}
            >
              Individual
            </button>
            <button
              onClick={() => setViewMode('strategies')}
              className={clsx(
                'px-3 py-1.5 text-sm font-display rounded-md transition-all',
                viewMode === 'strategies'
                  ? 'bg-accent-cyan text-bg-primary'
                  : 'text-text-secondary hover:text-text-primary'
              )}
            >
              Strategies
            </button>
          </div>

          {/* Status Filter */}
          <div className="flex bg-bg-card rounded-lg p-1">
            {(['open', 'closed', 'all'] as const).map((status) => (
              <button
                key={status}
                onClick={() => setStatusFilter(status)}
                className={clsx(
                  'px-3 py-1.5 text-sm font-display rounded-md transition-all capitalize',
                  statusFilter === status
                    ? 'bg-accent-cyan text-bg-primary'
                    : 'text-text-secondary hover:text-text-primary'
                )}
              >
                {status}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Table */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="card"
      >
        {viewMode === 'positions' ? (
          positionsLoading ? (
            <TableSkeleton />
          ) : (
            <DataTable
              data={positions}
              columns={positionColumns}
              emptyMessage="No positions found"
            />
          )
        ) : (
          strategiesLoading ? (
            <TableSkeleton />
          ) : (
            <DataTable
              data={strategyPositions}
              columns={strategyColumns}
              emptyMessage="No strategy positions found"
            />
          )
        )}
      </motion.div>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="animate-pulse space-y-3">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="h-12 bg-bg-secondary rounded" />
      ))}
    </div>
  );
}

export default Positions;
