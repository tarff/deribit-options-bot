import type { LiveUpdate, MarketData, Position, AccountInfo, PortfolioGreeks } from './types';

type MessageHandler = (update: LiveUpdate) => void;
type ConnectionHandler = (connected: boolean) => void;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 10;
  private reconnectDelay: number = 1000;
  private messageHandlers: Set<MessageHandler> = new Set();
  private connectionHandlers: Set<ConnectionHandler> = new Set();
  private isIntentionallyClosed: boolean = false;

  constructor() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const token = import.meta.env.VITE_DASHBOARD_API_TOKEN as string | undefined;
    const query = token ? `?token=${encodeURIComponent(token)}` : '';
    this.url = `${protocol}//${host}/api/ws/live${query}`;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    this.isIntentionallyClosed = false;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('WebSocket connected');
        this.reconnectAttempts = 0;
        this.notifyConnectionHandlers(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const update: LiveUpdate = JSON.parse(event.data);
          this.notifyMessageHandlers(update);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      this.ws.onclose = (event) => {
        console.log('WebSocket closed:', event.code, event.reason);
        this.notifyConnectionHandlers(false);

        if (!this.isIntentionallyClosed && this.reconnectAttempts < this.maxReconnectAttempts) {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this.isIntentionallyClosed = true;
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  private scheduleReconnect(): void {
    this.reconnectAttempts++;
    const delay = Math.min(
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
      30000
    );
    console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    setTimeout(() => this.connect(), delay);
  }

  private notifyMessageHandlers(update: LiveUpdate): void {
    this.messageHandlers.forEach((handler) => {
      try {
        handler(update);
      } catch (error) {
        console.error('Error in message handler:', error);
      }
    });
  }

  private notifyConnectionHandlers(connected: boolean): void {
    this.connectionHandlers.forEach((handler) => {
      try {
        handler(connected);
      } catch (error) {
        console.error('Error in connection handler:', error);
      }
    });
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionHandlers.add(handler);
    return () => this.connectionHandlers.delete(handler);
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

export const wsManager = new WebSocketManager();

// Type-safe update extractors
export function isMarketUpdate(update: LiveUpdate): update is LiveUpdate & { data: MarketData } {
  return update.type === 'market';
}

export function isPositionsUpdate(update: LiveUpdate): update is LiveUpdate & { data: Position[] } {
  return update.type === 'positions';
}

export function isAccountUpdate(update: LiveUpdate): update is LiveUpdate & { data: AccountInfo } {
  return update.type === 'account';
}

export function isGreeksUpdate(update: LiveUpdate): update is LiveUpdate & { data: PortfolioGreeks } {
  return update.type === 'greeks';
}

export default wsManager;
