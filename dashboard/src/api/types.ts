// Market data types
export interface MarketData {
  price: number;
  price_change_24h: number;
  currency: string;
  is_linear?: boolean;
  dvol: number;
  iv_rank: number;
  iv_percentile: number;
  realized_vol: number;
  iv_rv_spread: number;
  regime: MarketRegime;
  timestamp: string;
  // Legacy fields for backwards compatibility
  btc_price?: number;
  btc_change_24h?: number;
}

/**
 * Get the number of decimal places for value display based on settlement type.
 * Linear (USDC): 2 decimals (dollar amounts)
 * Inverse (crypto): 4 decimals (crypto fractions)
 */
export function getValueDecimals(isLinear?: boolean): number {
  return isLinear ? 2 : 4;
}

/**
 * Get the unit label for settlement type.
 */
export function getSettlementUnit(isLinear?: boolean, currency?: string): string {
  return isLinear ? 'USDC' : (currency ?? 'BTC');
}

export type MarketRegime =
  | 'EXTREME_FEAR'
  | 'HIGH_IV_OVERPRICED'
  | 'LOW_IV_UNDERPRICED'
  | 'VOLATILE_FAIR'
  | 'NEUTRAL';

// Account types
export interface AccountInfo {
  equity: number;
  balance: number;
  margin_balance: number;
  available_funds: number;
  initial_margin: number;
  maintenance_margin: number;
  margin_usage_pct: number;
  unrealized_pnl: number;
  realized_pnl_today: number;
}

// Position types
export interface Position {
  id: string;
  instrument_name: string;
  direction: 'long' | 'short';
  size: number;
  average_price: number;
  mark_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  strategy_type?: string;
  strategy_id?: string;
  opened_at: string;
}

export interface StrategyPosition {
  strategy_id: string;
  strategy_type: string;
  legs: Position[];
  total_pnl: number;
  portfolio_delta: number;
  portfolio_gamma: number;
  portfolio_theta: number;
  portfolio_vega: number;
  status: 'open' | 'closed';
  opened_at: string;
  closed_at?: string;
}

// Greeks aggregation
export interface PortfolioGreeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

// Trade types
export interface Trade {
  id: string;
  timestamp: string;
  instrument_name: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  fee: number;
  pnl?: number;
  strategy_type?: string;
  order_type: string;
}

// Historical data types
export interface OHLCVData {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface HistoricalData {
  price: OHLCVData[];
  dvol: Array<{ timestamp: string; value: number }>;
  // Legacy key for backwards compatibility
  btc?: OHLCVData[];
}

// Stats types
export interface TradeStats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  max_drawdown: number;
  by_strategy: Record<string, StrategyStats>;
}

export interface StrategyStats {
  trades: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
}

export interface RegimeStats {
  regime: MarketRegime;
  count: number;
  percentage: number;
}

// WebSocket message types
export interface LiveUpdate {
  type: 'market' | 'positions' | 'account' | 'greeks';
  data: MarketData | Position[] | AccountInfo | PortfolioGreeks;
  timestamp: string;
}

// API response wrapper
export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error?: string;
}
