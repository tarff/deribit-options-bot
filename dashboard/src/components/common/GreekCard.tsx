import { motion } from 'framer-motion';
import clsx from 'clsx';

type GreekType = 'delta' | 'gamma' | 'theta' | 'vega';

interface GreekCardProps {
  type: GreekType;
  value: number;
  className?: string;
}

const greekConfig: Record<GreekType, { symbol: string; color: string; description: string }> = {
  delta: {
    symbol: 'Δ',
    color: '#00D9FF',
    description: 'Directional exposure',
  },
  gamma: {
    symbol: 'Γ',
    color: '#8B5CF6',
    description: 'Delta sensitivity',
  },
  theta: {
    symbol: 'Θ',
    color: '#FFB800',
    description: 'Time decay',
  },
  vega: {
    symbol: 'ν',
    color: '#00FF88',
    description: 'Volatility sensitivity',
  },
};

export function GreekCard({ type, value, className }: GreekCardProps) {
  const config = greekConfig[type];
  const isNegative = value < 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ borderColor: config.color, boxShadow: `0 0 20px ${config.color}25` }}
      transition={{ duration: 0.2 }}
      className={clsx(
        'card card-hover flex items-center gap-4',
        className
      )}
    >
      <div
        className="w-12 h-12 rounded-lg flex items-center justify-center text-2xl font-mono font-bold"
        style={{
          backgroundColor: `${config.color}15`,
          color: config.color,
        }}
      >
        {config.symbol}
      </div>
      <div className="flex-1">
        <p className="text-sm text-text-muted font-display uppercase tracking-wider">
          {type}
        </p>
        <p
          className={clsx(
            'text-xl font-mono font-semibold tabular-nums',
            isNegative ? 'text-loss' : 'text-text-primary'
          )}
        >
          {value >= 0 ? '+' : ''}{value.toFixed(4)}
        </p>
      </div>
    </motion.div>
  );
}

interface PortfolioGreeksDisplayProps {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  className?: string;
}

export function PortfolioGreeksDisplay({
  delta,
  gamma,
  theta,
  vega,
  className,
}: PortfolioGreeksDisplayProps) {
  return (
    <div className={clsx('grid grid-cols-2 lg:grid-cols-4 gap-4', className)}>
      <GreekCard type="delta" value={delta} />
      <GreekCard type="gamma" value={gamma} />
      <GreekCard type="theta" value={theta} />
      <GreekCard type="vega" value={vega} />
    </div>
  );
}

export default GreekCard;
