import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { colors } from '../../styles/theme';

interface PnlDataPoint {
  date: string;
  pnl: number;
  cumulative: number;
}

interface PnlChartProps {
  data: PnlDataPoint[];
  height?: number;
  showCumulative?: boolean;
  decimals?: number;
}

export function PnlChart({
  data,
  height = 300,
  showCumulative = true,
  decimals = 4,
}: PnlChartProps) {
  const dataKey = showCumulative ? 'cumulative' : 'pnl';
  const isPositive = data.length > 0 && data[data.length - 1][dataKey] >= 0;

  return (
    <div className="card">
      <h3 className="text-sm font-display uppercase tracking-wider text-text-muted mb-4">
        {showCumulative ? 'Cumulative P&L' : 'Daily P&L'}
      </h3>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="profitGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={colors.profitGreen} stopOpacity={0.3} />
              <stop offset="95%" stopColor={colors.profitGreen} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="lossGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={colors.lossRed} stopOpacity={0.3} />
              <stop offset="95%" stopColor={colors.lossRed} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke={colors.border}
            vertical={false}
          />
          <XAxis
            dataKey="date"
            stroke={colors.textMuted}
            fontSize={10}
            fontFamily="JetBrains Mono"
            tickLine={false}
            axisLine={{ stroke: colors.border }}
          />
          <YAxis
            stroke={colors.textMuted}
            fontSize={10}
            fontFamily="JetBrains Mono"
            tickLine={false}
            axisLine={{ stroke: colors.border }}
            tickFormatter={(value) => value.toFixed(decimals)}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: colors.bgSecondary,
              border: `1px solid ${colors.border}`,
              borderRadius: '8px',
              fontFamily: 'JetBrains Mono',
            }}
            labelStyle={{ color: colors.textMuted }}
            formatter={(value: number) => [
              <span style={{ color: value >= 0 ? colors.profitGreen : colors.lossRed }}>
                {value.toFixed(decimals)}
              </span>,
              showCumulative ? 'Cumulative' : 'P&L',
            ]}
          />
          <ReferenceLine y={0} stroke={colors.textMuted} strokeDasharray="3 3" />
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={isPositive ? colors.profitGreen : colors.lossRed}
            fill={isPositive ? 'url(#profitGradient)' : 'url(#lossGradient)'}
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export default PnlChart;
