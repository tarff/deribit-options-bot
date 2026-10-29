import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { useState } from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';

interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  className?: string;
  emptyMessage?: string;
}

export function DataTable<T>({
  data,
  columns,
  className,
  emptyMessage = 'No data available',
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState('');

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      globalFilter,
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  return (
    <div className={clsx('overflow-hidden', className)}>
      {/* Search input */}
      <div className="mb-4">
        <input
          type="text"
          placeholder="Search..."
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          className="w-full max-w-xs px-3 py-2 bg-bg-secondary border border-border rounded-lg
                     text-text-primary font-mono text-sm
                     focus:outline-none focus:border-accent-cyan focus:shadow-glow-cyan
                     placeholder:text-text-muted"
        />
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-border">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className={clsx(
                      'px-4 py-3 text-left text-xs font-display uppercase tracking-wider text-text-muted',
                      header.column.getCanSort() && 'cursor-pointer select-none hover:text-text-secondary'
                    )}
                  >
                    <div className="flex items-center gap-2">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() && (
                        <span className="text-accent-cyan">
                          {header.column.getIsSorted() === 'asc' ? '▲' : '▼'}
                        </span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-8 text-center text-text-muted"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row, index) => (
                <motion.tr
                  key={row.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.02 }}
                  className="border-b border-border/50 hover:bg-bg-secondary/50 transition-colors"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3 font-mono text-sm">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </motion.tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Cell renderer utilities
export function PnlCell({ value, decimals = 4 }: { value: number | null | undefined; decimals?: number }) {
  if (value == null) {
    return <span className="text-text-muted">—</span>;
  }
  const isPositive = value >= 0;
  return (
    <span
      className={clsx(
        'font-mono tabular-nums',
        isPositive ? 'text-profit' : 'text-loss'
      )}
    >
      {isPositive ? '+' : ''}{value.toFixed(decimals)}
    </span>
  );
}

export function PriceCell({ value, decimals = 4, suffix = '' }: { value: number; decimals?: number; suffix?: string }) {
  return (
    <span className="font-mono tabular-nums text-text-primary">
      {value.toFixed(decimals)}{suffix && ` ${suffix}`}
    </span>
  );
}

export function SideCell({ side }: { side: 'buy' | 'sell' | 'long' | 'short' }) {
  const isLong = side === 'buy' || side === 'long';
  return (
    <span
      className={clsx(
        'px-2 py-0.5 rounded text-xs font-display uppercase',
        isLong ? 'bg-profit/15 text-profit' : 'bg-loss/15 text-loss'
      )}
    >
      {side}
    </span>
  );
}

export default DataTable;
