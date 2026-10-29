import { motion } from 'framer-motion';
import clsx from 'clsx';
import { useIsConnected } from '../../stores/useAppStore';

interface HeaderProps {
  title?: string;
}

export function Header({ title = 'Dashboard' }: HeaderProps) {
  const isConnected = useIsConnected();

  return (
    <header className="h-16 bg-bg-secondary border-b border-border flex items-center justify-between px-6">
      <h1 className="text-xl font-display font-semibold text-text-primary">{title}</h1>

      <div className="flex items-center gap-4">
        {/* Connection Status */}
        <ConnectionStatus isConnected={isConnected} />

        {/* Time */}
        <Clock />
      </div>
    </header>
  );
}

function ConnectionStatus({ isConnected }: { isConnected: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <motion.div
        animate={{
          scale: isConnected ? [1, 1.2, 1] : 1,
          opacity: isConnected ? 1 : 0.5,
        }}
        transition={{
          repeat: isConnected ? Infinity : 0,
          duration: 2,
        }}
        className={clsx(
          'w-2 h-2 rounded-full',
          isConnected ? 'bg-profit' : 'bg-loss'
        )}
      />
      <span
        className={clsx(
          'text-sm font-mono',
          isConnected ? 'text-profit' : 'text-loss'
        )}
      >
        {isConnected ? 'LIVE' : 'DISCONNECTED'}
      </span>
    </div>
  );
}

function Clock() {
  const now = new Date();
  const timeString = now.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });

  return (
    <div className="text-sm font-mono text-text-secondary">
      <span className="text-text-muted">UTC </span>
      {timeString}
    </div>
  );
}

export default Header;
