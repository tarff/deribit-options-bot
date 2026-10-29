/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: '#0D0D0F',
          secondary: '#151518',
          card: '#1E1E24',
        },
        border: {
          DEFAULT: '#2A2A32',
          hover: '#3A3A44',
        },
        text: {
          primary: '#FFFFFF',
          secondary: '#A0A0B0',
          muted: '#6B6B7B',
        },
        accent: {
          cyan: '#00D9FF',
          'cyan-dim': '#00D9FF80',
        },
        profit: '#00FF88',
        loss: '#FF3366',
        warning: '#FFB800',
        btc: '#F7931A',
        regime: {
          'extreme-fear': '#FF3366',
          'high-stress': '#FF6B35',
          'high-iv': '#FFB800',
          'low-iv': '#00D9FF',
          'volatile-fair': '#8B5CF6',
          'neutral': '#00FF88',
        },
      },
      fontFamily: {
        display: ['Outfit', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': '0 0 20px rgba(0, 217, 255, 0.15)',
        'glow-profit': '0 0 20px rgba(0, 255, 136, 0.15)',
        'glow-loss': '0 0 20px rgba(255, 51, 102, 0.15)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(0, 217, 255, 0.2)' },
          '100%': { boxShadow: '0 0 20px rgba(0, 217, 255, 0.4)' },
        },
      },
    },
  },
  plugins: [],
}
