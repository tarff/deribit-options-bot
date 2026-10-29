import { motion } from 'framer-motion';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts';
import { useTradeStats, useRegimeStats } from '../api/hooks/useTradeStats';
import { MetricCard } from '../components/common/MetricCard';
import { PnlChart } from '../components/charts/PnlChart';
import { useAppStore } from '../stores/useAppStore';
import { getValueDecimals } from '../api/types';
import { colors, regimeColors } from '../styles/theme';
import type { MarketRegime } from '../api/types';

export function Analytics() {
  const { tradeStats, isLoading: statsLoading } = useTradeStats();
  const { regimeStats, isLoading: regimeLoading } = useRegimeStats(30);
  const marketData = useAppStore((state) => state.marketData);
  const decimals = getValueDecimals(marketData?.is_linear);

  // Generate mock cumulative P&L data for chart
  // In production, this would come from the API
  const pnlData = generateMockPnlData();

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-display font-semibold text-text-primary">
        Performance Analytics
      </h2>

      {/* Key Metrics */}
      {statsLoading || !tradeStats ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="card h-24 animate-pulse" />
          ))}
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="grid grid-cols-2 lg:grid-cols-4 gap-4"
        >
          <MetricCard
            label="Total P&L"
            value={`${tradeStats.total_pnl >= 0 ? '+' : ''}${tradeStats.total_pnl.toFixed(decimals)}`}
            variant={tradeStats.total_pnl >= 0 ? 'profit' : 'loss'}
          />
          <MetricCard
            label="Win Rate"
            value={`${tradeStats.win_rate.toFixed(1)}%`}
            subValue={`${tradeStats.winning_trades}W / ${tradeStats.losing_trades}L`}
            variant={tradeStats.win_rate >= 50 ? 'profit' : 'loss'}
          />
          <MetricCard
            label="Profit Factor"
            value={tradeStats.profit_factor.toFixed(2)}
            variant={tradeStats.profit_factor >= 1 ? 'profit' : 'loss'}
          />
          <MetricCard
            label="Max Drawdown"
            value={`${tradeStats.max_drawdown.toFixed(1)}%`}
            variant="warning"
          />
        </motion.div>
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* P&L Chart */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <PnlChart data={pnlData} height={300} showCumulative decimals={decimals} />
        </motion.div>

        {/* Regime Distribution */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="card"
        >
          <h3 className="text-sm font-display uppercase tracking-wider text-text-muted mb-4">
            Regime Distribution (30d)
          </h3>
          {regimeLoading ? (
            <div className="h-[250px] animate-pulse bg-bg-secondary rounded" />
          ) : (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={regimeStats}
                  dataKey="percentage"
                  nameKey="regime"
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={90}
                  paddingAngle={2}
                  label={({ percentage }) => `${percentage.toFixed(0)}%`}
                  labelLine={false}
                >
                  {regimeStats.map((entry) => (
                    <Cell
                      key={entry.regime}
                      fill={regimeColors[entry.regime as MarketRegime] || colors.textMuted}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: colors.bgSecondary,
                    border: `1px solid ${colors.border}`,
                    borderRadius: '8px',
                    fontFamily: 'JetBrains Mono',
                  }}
                  formatter={(value: number) => [`${value.toFixed(1)}%`, 'Time']}
                />
              </PieChart>
            </ResponsiveContainer>
          )}

          {/* Legend */}
          <div className="flex flex-wrap gap-3 mt-4 justify-center">
            {regimeStats.map((stat) => (
              <div key={stat.regime} className="flex items-center gap-1.5">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: regimeColors[stat.regime as MarketRegime] }}
                />
                <span className="text-xs text-text-secondary">
                  {stat.regime.replace(/_/g, ' ')}
                </span>
              </div>
            ))}
          </div>
        </motion.div>
      </div>

      {/* Strategy Breakdown */}
      {tradeStats && Object.keys(tradeStats.by_strategy).length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="card"
        >
          <h3 className="text-sm font-display uppercase tracking-wider text-text-muted mb-4">
            Strategy Performance
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={Object.entries(tradeStats.by_strategy).map(([name, stats]) => ({
                name,
                pnl: stats.total_pnl,
                trades: stats.trades,
                winRate: stats.win_rate,
              }))}
              margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
              <XAxis
                dataKey="name"
                stroke={colors.textMuted}
                fontSize={10}
                fontFamily="JetBrains Mono"
                tickLine={false}
              />
              <YAxis
                stroke={colors.textMuted}
                fontSize={10}
                fontFamily="JetBrains Mono"
                tickLine={false}
                tickFormatter={(value) => value.toFixed(decimals)}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: colors.bgSecondary,
                  border: `1px solid ${colors.border}`,
                  borderRadius: '8px',
                  fontFamily: 'JetBrains Mono',
                }}
                formatter={(value: number, name: string) => {
                  if (name === 'pnl') return [value.toFixed(decimals), 'P&L'];
                  if (name === 'trades') return [value, 'Trades'];
                  if (name === 'winRate') return [`${value.toFixed(1)}%`, 'Win Rate'];
                  return [value, name];
                }}
              />
              <Bar
                dataKey="pnl"
                fill={colors.accentCyan}
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </motion.div>
      )}

      {/* Win/Loss Stats */}
      {tradeStats && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="grid grid-cols-2 lg:grid-cols-4 gap-4"
        >
          <div className="card">
            <p className="text-xs text-text-muted uppercase">Avg Win</p>
            <p className="text-xl font-mono font-semibold text-profit mt-1">
              +{tradeStats.avg_win.toFixed(decimals)}
            </p>
          </div>
          <div className="card">
            <p className="text-xs text-text-muted uppercase">Avg Loss</p>
            <p className="text-xl font-mono font-semibold text-loss mt-1">
              -{Math.abs(tradeStats.avg_loss).toFixed(decimals)}
            </p>
          </div>
          <div className="card">
            <p className="text-xs text-text-muted uppercase">Total Trades</p>
            <p className="text-xl font-mono font-semibold text-text-primary mt-1">
              {tradeStats.total_trades}
            </p>
          </div>
          <div className="card">
            <p className="text-xs text-text-muted uppercase">Risk/Reward</p>
            <p className="text-xl font-mono font-semibold text-accent-cyan mt-1">
              {(tradeStats.avg_win / Math.abs(tradeStats.avg_loss || 1)).toFixed(2)}
            </p>
          </div>
        </motion.div>
      )}
    </div>
  );
}

// Mock data generator for demo purposes
function generateMockPnlData() {
  const data = [];
  let cumulative = 0;

  for (let i = 30; i >= 0; i--) {
    const date = new Date();
    date.setDate(date.getDate() - i);
    const pnl = (Math.random() - 0.4) * 500; // Slightly positive bias
    cumulative += pnl;

    data.push({
      date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      pnl: Math.round(pnl * 100) / 100,
      cumulative: Math.round(cumulative * 100) / 100,
    });
  }

  return data;
}

export default Analytics;
