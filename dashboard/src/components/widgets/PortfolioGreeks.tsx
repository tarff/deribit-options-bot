import { motion } from 'framer-motion';
import { PortfolioGreeksDisplay } from '../common/GreekCard';
import type { PortfolioGreeks as PortfolioGreeksType } from '../../api/types';

interface PortfolioGreeksProps {
  greeks: PortfolioGreeksType | null;
  isLoading?: boolean;
}

export function PortfolioGreeks({ greeks, isLoading }: PortfolioGreeksProps) {
  if (isLoading || !greeks) {
    return <PortfolioGreeksSkeleton />;
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-4"
    >
      <h2 className="text-lg font-display font-semibold text-text-primary">
        Portfolio Greeks
      </h2>

      <PortfolioGreeksDisplay
        delta={greeks.delta}
        gamma={greeks.gamma}
        theta={greeks.theta}
        vega={greeks.vega}
      />

      {/* Risk Summary */}
      <div className="card bg-bg-secondary/50">
        <h3 className="text-sm font-display uppercase tracking-wider text-text-muted mb-3">
          Risk Summary
        </h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-text-muted">Directional Bias:</span>
            <span className="ml-2 font-mono text-text-primary">
              {greeks.delta > 0.1 ? 'Bullish' : greeks.delta < -0.1 ? 'Bearish' : 'Neutral'}
            </span>
          </div>
          <div>
            <span className="text-text-muted">Gamma Profile:</span>
            <span className="ml-2 font-mono text-text-primary">
              {greeks.gamma > 0 ? 'Long Gamma' : greeks.gamma < 0 ? 'Short Gamma' : 'Flat'}
            </span>
          </div>
          <div>
            <span className="text-text-muted">Time Decay:</span>
            <span className={`ml-2 font-mono ${greeks.theta >= 0 ? 'text-profit' : 'text-loss'}`}>
              {greeks.theta >= 0 ? 'Collecting' : 'Paying'} ({Math.abs(greeks.theta).toFixed(4)}/day)
            </span>
          </div>
          <div>
            <span className="text-text-muted">Vol Exposure:</span>
            <span className="ml-2 font-mono text-text-primary">
              {greeks.vega > 0 ? 'Long Vol' : greeks.vega < 0 ? 'Short Vol' : 'Neutral'}
            </span>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function PortfolioGreeksSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-8 bg-bg-card rounded w-48" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="card h-20" />
        ))}
      </div>
    </div>
  );
}

export default PortfolioGreeks;
