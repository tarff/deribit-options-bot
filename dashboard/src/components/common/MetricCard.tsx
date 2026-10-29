import { motion } from 'framer-motion';
import clsx from 'clsx';

interface MetricCardProps {
  label: string;
  value: string | number;
  subValue?: string;
  trend?: 'up' | 'down' | 'neutral';
  trendValue?: string;
  icon?: React.ReactNode;
  variant?: 'default' | 'profit' | 'loss' | 'warning' | 'cyan';
  className?: string;
}

export function MetricCard({
  label,
  value,
  subValue,
  trend,
  trendValue,
  icon,
  variant = 'default',
  className,
}: MetricCardProps) {
  const variantStyles = {
    default: 'border-border',
    profit: 'border-profit/30 shadow-glow-profit',
    loss: 'border-loss/30 shadow-glow-loss',
    warning: 'border-warning/30',
    cyan: 'border-accent-cyan/30 shadow-glow-cyan',
  };

  const valueStyles = {
    default: 'text-text-primary',
    profit: 'text-profit',
    loss: 'text-loss',
    warning: 'text-warning',
    cyan: 'text-accent-cyan',
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ borderColor: '#00D9FF', boxShadow: '0 0 20px rgba(0,217,255,0.15)' }}
      transition={{ duration: 0.2 }}
      className={clsx(
        'card card-hover',
        variantStyles[variant],
        className
      )}
    >
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className="text-sm text-text-muted font-display uppercase tracking-wider">
            {label}
          </p>
          <p className={clsx('text-2xl font-mono font-semibold tabular-nums', valueStyles[variant])}>
            {value}
          </p>
          {subValue && (
            <p className="text-sm text-text-secondary font-mono">{subValue}</p>
          )}
        </div>
        {icon && (
          <div className="text-text-muted">{icon}</div>
        )}
      </div>

      {trend && trendValue && (
        <div className="mt-3 flex items-center gap-1">
          <span
            className={clsx(
              'text-sm font-mono',
              trend === 'up' && 'text-profit',
              trend === 'down' && 'text-loss',
              trend === 'neutral' && 'text-text-muted'
            )}
          >
            {trend === 'up' && '▲'}
            {trend === 'down' && '▼'}
            {trend === 'neutral' && '–'}
            {' '}{trendValue}
          </span>
        </div>
      )}
    </motion.div>
  );
}

export default MetricCard;
