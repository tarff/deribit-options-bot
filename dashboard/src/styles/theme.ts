export const colors = {
  bgPrimary: '#0D0D0F',
  bgSecondary: '#151518',
  bgCard: '#1E1E24',
  border: '#2A2A32',
  borderHover: '#3A3A44',
  textPrimary: '#FFFFFF',
  textSecondary: '#A0A0B0',
  textMuted: '#6B6B7B',
  accentCyan: '#00D9FF',
  accentCyanDim: '#00D9FF80',
  profitGreen: '#00FF88',
  lossRed: '#FF3366',
  warningAmber: '#FFB800',
  btcOrange: '#F7931A',
} as const;

export const regimeColors: Record<string, string> = {
  EXTREME_FEAR: '#FF3366',
  HIGH_IV_OVERPRICED: '#FFB800',
  LOW_IV_UNDERPRICED: '#00D9FF',
  VOLATILE_FAIR: '#8B5CF6',
  NEUTRAL: '#00FF88',
};

export const chartColors = {
  btcLine: colors.btcOrange,
  dvolLine: colors.accentCyan,
  profitArea: 'rgba(0, 255, 136, 0.2)',
  lossArea: 'rgba(255, 51, 102, 0.2)',
  gridLines: '#2A2A32',
  crosshair: '#4A4A54',
};
