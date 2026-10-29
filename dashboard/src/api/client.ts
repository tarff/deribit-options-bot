import axios, { AxiosInstance } from 'axios';
import type {
  MarketData,
  AccountInfo,
  Position,
  StrategyPosition,
  Trade,
  HistoricalData,
  TradeStats,
  RegimeStats,
  PortfolioGreeks,
} from './types';

const API_BASE_URL = '/api';
const DASHBOARD_TOKEN = import.meta.env.VITE_DASHBOARD_API_TOKEN as string | undefined;

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json',
        ...(DASHBOARD_TOKEN ? { Authorization: `Bearer ${DASHBOARD_TOKEN}` } : {}),
      },
    });

    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        console.error('API Error:', error.response?.data || error.message);
        return Promise.reject(error);
      }
    );
  }

  // Market endpoints
  async getMarketData(): Promise<MarketData> {
    const response = await this.client.get<MarketData>('/market/live');
    return response.data;
  }

  // Account endpoints
  async getAccount(): Promise<AccountInfo> {
    const response = await this.client.get<AccountInfo>('/account');
    return response.data;
  }

  // Position endpoints
  async getPositions(status: 'open' | 'closed' | 'all' = 'open'): Promise<Position[]> {
    const response = await this.client.get<Position[]>('/positions', {
      params: { status },
    });
    return response.data;
  }

  async getLivePositions(): Promise<Position[]> {
    const response = await this.client.get<Position[]>('/positions/live');
    return response.data;
  }

  async getStrategyPositions(status: 'open' | 'closed' | 'all' = 'open'): Promise<StrategyPosition[]> {
    const response = await this.client.get<StrategyPosition[]>('/positions/strategies', {
      params: { status },
    });
    return response.data;
  }

  async getPortfolioGreeks(): Promise<PortfolioGreeks> {
    const response = await this.client.get<PortfolioGreeks>('/positions/greeks');
    return response.data;
  }

  // Trade endpoints
  async getTrades(limit: number = 100, offset: number = 0): Promise<Trade[]> {
    const response = await this.client.get<Trade[]>('/trades', {
      params: { limit, offset },
    });
    return response.data;
  }

  async getTradesByStrategy(strategyType: string): Promise<Trade[]> {
    const response = await this.client.get<Trade[]>('/trades', {
      params: { strategy_type: strategyType },
    });
    return response.data;
  }

  // Historical endpoints
  async getHistoricalData(
    startDate: string,
    endDate: string,
    resolution: string = '1h'
  ): Promise<HistoricalData> {
    const response = await this.client.get<HistoricalData>('/historical', {
      params: { start: startDate, end: endDate, resolution },
    });
    return response.data;
  }

  // Stats endpoints
  async getTradeStats(): Promise<TradeStats> {
    const response = await this.client.get<TradeStats>('/stats');
    return response.data;
  }

  async getRegimeStats(days: number = 30): Promise<RegimeStats[]> {
    const response = await this.client.get<RegimeStats[]>('/stats/regimes', {
      params: { days },
    });
    return response.data;
  }
}

export const apiClient = new ApiClient();
export default apiClient;
