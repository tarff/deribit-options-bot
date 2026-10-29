import { useMemo } from 'react';
import { type ColumnDef } from '@tanstack/react-table';
import { motion } from 'framer-motion';
import { DataTable, PnlCell, SideCell, PriceCell } from '../common/DataTable';
import { useAppStore } from '../../stores/useAppStore';
import { getValueDecimals } from '../../api/types';
import type { Position } from '../../api/types';

interface PositionsTableProps {
  positions: Position[];
  isLoading?: boolean;
}

export function PositionsTable({ positions, isLoading }: PositionsTableProps) {
  const marketData = useAppStore((state) => state.marketData);
  const isLinear = marketData?.is_linear;
  const decimals = getValueDecimals(isLinear);

  const columns = useMemo<ColumnDef<Position, unknown>[]>(
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
        header: 'Avg Price',
        cell: ({ row }) => <PriceCell value={row.original.average_price} decimals={decimals} />,
      },
      {
        accessorKey: 'mark_price',
        header: 'Mark Price',
        cell: ({ row }) => <PriceCell value={row.original.mark_price} decimals={decimals} />,
      },
      {
        accessorKey: 'unrealized_pnl',
        header: 'Unrealized P&L',
        cell: ({ row }) => <PnlCell value={row.original.unrealized_pnl} decimals={decimals} />,
      },
      {
        accessorKey: 'delta',
        header: 'Delta',
        cell: ({ row }) => (
          <span className="text-accent-cyan tabular-nums">
            {row.original.delta.toFixed(4)}
          </span>
        ),
      },
      {
        accessorKey: 'strategy_type',
        header: 'Strategy',
        cell: ({ row }) => (
          <span className="text-text-secondary text-xs uppercase">
            {row.original.strategy_type || '—'}
          </span>
        ),
      },
    ],
    [decimals]
  );

  if (isLoading) {
    return <PositionsTableSkeleton />;
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="card"
    >
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-display font-semibold text-text-primary">
          Open Positions
        </h2>
        <span className="text-sm text-text-muted">
          {positions.length} position{positions.length !== 1 ? 's' : ''}
        </span>
      </div>

      <DataTable
        data={positions}
        columns={columns}
        emptyMessage="No open positions"
      />
    </motion.div>
  );
}

function PositionsTableSkeleton() {
  return (
    <div className="card animate-pulse">
      <div className="h-8 bg-bg-secondary rounded w-48 mb-4" />
      <div className="space-y-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-12 bg-bg-secondary rounded" />
        ))}
      </div>
    </div>
  );
}

export default PositionsTable;
