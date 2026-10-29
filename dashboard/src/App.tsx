import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { Dashboard } from './pages/Dashboard';
import { Charts } from './pages/Charts';
import { Positions } from './pages/Positions';
import { TradeHistory } from './pages/TradeHistory';
import { Analytics } from './pages/Analytics';
import { useAppStore } from './stores/useAppStore';

function App() {
  const sidebarCollapsed = useAppStore((state) => state.sidebarCollapsed);

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-bg-primary">
        <Sidebar />
        <div
          className="transition-all duration-200"
          style={{ marginLeft: sidebarCollapsed ? 64 : 240 }}
        >
          <Routes>
            <Route
              path="/"
              element={
                <PageLayout title="Dashboard">
                  <Dashboard />
                </PageLayout>
              }
            />
            <Route
              path="/charts"
              element={
                <PageLayout title="Charts">
                  <Charts />
                </PageLayout>
              }
            />
            <Route
              path="/positions"
              element={
                <PageLayout title="Positions">
                  <Positions />
                </PageLayout>
              }
            />
            <Route
              path="/trades"
              element={
                <PageLayout title="Trade History">
                  <TradeHistory />
                </PageLayout>
              }
            />
            <Route
              path="/analytics"
              element={
                <PageLayout title="Analytics">
                  <Analytics />
                </PageLayout>
              }
            />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}

interface PageLayoutProps {
  title: string;
  children: React.ReactNode;
}

function PageLayout({ title, children }: PageLayoutProps) {
  return (
    <div className="min-h-screen flex flex-col">
      <Header title={title} />
      <motion.main
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="flex-1 p-6"
      >
        {children}
      </motion.main>
    </div>
  );
}

export default App;
