import { useMarketData } from '../api/hooks/useMarketData';
import { useAccount } from '../api/hooks/useAccount';
import { usePositions } from '../api/hooks/usePositions';
import { MarketOverview } from '../components/widgets/MarketOverview';
import { AccountSummary } from '../components/widgets/AccountSummary';
import { PositionsTable } from '../components/widgets/PositionsTable';
import { PortfolioGreeks } from '../components/widgets/PortfolioGreeks';
import { useAppStore } from '../stores/useAppStore';

export function Dashboard() {
  const { marketData, isLoading: marketLoading } = useMarketData();
  const { account, isLoading: accountLoading } = useAccount();
  const { positions, isLoading: positionsLoading } = usePositions();
  const portfolioGreeks = useAppStore((state) => state.portfolioGreeks);

  return (
    <div className="space-y-6">
      {/* Market Overview Section */}
      <MarketOverview data={marketData} isLoading={marketLoading} />

      {/* Account & Greeks Row */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <AccountSummary account={account} isLoading={accountLoading} />
        <PortfolioGreeks greeks={portfolioGreeks} isLoading={positionsLoading} />
      </div>

      {/* Positions Table */}
      <PositionsTable positions={positions} isLoading={positionsLoading} />
    </div>
  );
}

export default Dashboard;
