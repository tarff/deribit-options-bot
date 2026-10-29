import { motion } from 'framer-motion';
import clsx from 'clsx';
import type { MarketRegime } from '../../api/types';

interface RegimeBadgeProps {
  regime: MarketRegime;
  size?: 'sm' | 'md' | 'lg';
  showGlow?: boolean;
  className?: string;
}

const regimeConfig: Record<MarketRegime, { label: string; color: string; bgColor: string }> = {
  EXTREME_FEAR: {
    label: 'Extreme Fear',
    color: '#FF3366',
    bgColor: 'rgba(255, 51, 102, 0.15)',
  },
  HIGH_IV_OVERPRICED: {
    label: 'High IV',
    color: '#FFB800',
    bgColor: 'rgba(255, 184, 0, 0.15)',
  },
  LOW_IV_UNDERPRICED: {
    label: 'Low IV',
    color: '#00D9FF',
    bgColor: 'rgba(0, 217, 255, 0.15)',
  },
  VOLATILE_FAIR: {
    label: 'Volatile Fair',
    color: '#8B5CF6',
    bgColor: 'rgba(139, 92, 246, 0.15)',
  },
  NEUTRAL: {
    label: 'Neutral',
    color: '#00FF88',
    bgColor: 'rgba(0, 255, 136, 0.15)',
  },
};

const sizeStyles = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-3 py-1 text-sm',
  lg: 'px-4 py-2 text-base',
};

export function RegimeBadge({
  regime,
  size = 'md',
  showGlow = true,
  className,
}: RegimeBadgeProps) {
  const config = regimeConfig[regime];

  return (
    <motion.span
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full font-display font-medium',
        sizeStyles[size],
        className
      )}
      style={{
        backgroundColor: config.bgColor,
        color: config.color,
        boxShadow: showGlow ? `0 0 15px ${config.bgColor}` : 'none',
      }}
    >
      <span
        className="w-2 h-2 rounded-full animate-pulse"
        style={{ backgroundColor: config.color }}
      />
      {config.label}
    </motion.span>
  );
}

export function RegimeIndicator({ regime }: { regime: MarketRegime }) {
  const config = regimeConfig[regime];

  return (
    <div className="flex items-center gap-2">
      <motion.div
        animate={{
          boxShadow: [
            `0 0 5px ${config.color}40`,
            `0 0 15px ${config.color}60`,
            `0 0 5px ${config.color}40`,
          ],
        }}
        transition={{ duration: 2, repeat: Infinity }}
        className="w-3 h-3 rounded-full"
        style={{ backgroundColor: config.color }}
      />
      <span
        className="font-display font-medium"
        style={{ color: config.color }}
      >
        {config.label}
      </span>
    </div>
  );
}

export default RegimeBadge;
