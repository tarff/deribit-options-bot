import { create } from 'zustand';
import type {
  MarketData,
  AccountInfo,
  Position,
  PortfolioGreeks,
  TradeStats,
} from '../api/types';

interface AppState {
  // Connection state
  isConnected: boolean;
  setConnected: (connected: boolean) => void;

  // Market data
  marketData: MarketData | null;
  setMarketData: (data: MarketData) => void;

  // Account data
  account: AccountInfo | null;
  setAccount: (account: AccountInfo) => void;

  // Positions
  positions: Position[];
  setPositions: (positions: Position[]) => void;

  // Portfolio Greeks
  portfolioGreeks: PortfolioGreeks | null;
  setPortfolioGreeks: (greeks: PortfolioGreeks) => void;

  // Trade stats
  tradeStats: TradeStats | null;
  setTradeStats: (stats: TradeStats) => void;

  // UI state
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;

  // Data freshness tracking
  lastUpdated: Record<string, string>;
  setLastUpdated: (key: string, timestamp: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // Connection state
  isConnected: false,
  setConnected: (connected) => set({ isConnected: connected }),

  // Market data
  marketData: null,
  setMarketData: (data) =>
    set((state) => ({
      marketData: data,
      lastUpdated: { ...state.lastUpdated, market: data.timestamp },
    })),

  // Account data
  account: null,
  setAccount: (account) =>
    set((state) => ({
      account,
      lastUpdated: { ...state.lastUpdated, account: new Date().toISOString() },
    })),

  // Positions
  positions: [],
  setPositions: (positions) =>
    set((state) => ({
      positions,
      lastUpdated: { ...state.lastUpdated, positions: new Date().toISOString() },
    })),

  // Portfolio Greeks
  portfolioGreeks: null,
  setPortfolioGreeks: (greeks) =>
    set((state) => ({
      portfolioGreeks: greeks,
      lastUpdated: { ...state.lastUpdated, greeks: new Date().toISOString() },
    })),

  // Trade stats
  tradeStats: null,
  setTradeStats: (stats) =>
    set((state) => ({
      tradeStats: stats,
      lastUpdated: { ...state.lastUpdated, stats: new Date().toISOString() },
    })),

  // UI state
  sidebarCollapsed: false,
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

  // Data freshness
  lastUpdated: {},
  setLastUpdated: (key, timestamp) =>
    set((state) => ({
      lastUpdated: { ...state.lastUpdated, [key]: timestamp },
    })),
}));

// Selector hooks for performance
export const useMarketData = () => useAppStore((state) => state.marketData);
export const useAccount = () => useAppStore((state) => state.account);
export const usePositions = () => useAppStore((state) => state.positions);
export const usePortfolioGreeks = () => useAppStore((state) => state.portfolioGreeks);
export const useTradeStats = () => useAppStore((state) => state.tradeStats);
export const useIsConnected = () => useAppStore((state) => state.isConnected);
