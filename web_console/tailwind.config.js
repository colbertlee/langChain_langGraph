/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg0: 'var(--bg-0)',
        bg1: 'var(--bg-1)',
        bg2: 'var(--bg-2)',
        fg0: 'var(--fg-0)',
        fg1: 'var(--fg-1)',
        fg2: 'var(--fg-2)',
        accent1: 'var(--accent-1)',
        accent2: 'var(--accent-2)',
        danger: 'var(--danger)',
        success: 'var(--success)',
        warn: 'var(--warn)',
      },
      fontFamily: {
        display: ['Manrope', 'system-ui', 'sans-serif'],
        sans: ['Satoshi', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(255,255,255,0.04), 0 8px 30px -8px rgba(6,182,212,0.25)',
        glass: 'inset 0 1px 0 rgba(255,255,255,0.06), 0 1px 0 rgba(255,255,255,0.02)',
      },
      backgroundImage: {
        'accent-grad': 'var(--accent-grad)',
        'mesh': 'radial-gradient(at 12% 8%, rgba(6,182,212,0.18) 0px, transparent 50%), radial-gradient(at 88% 12%, rgba(59,130,246,0.16) 0px, transparent 50%), radial-gradient(at 50% 100%, rgba(168,85,247,0.10) 0px, transparent 60%)',
      },
      keyframes: {
        'pulse-soft': {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite',
        shimmer: 'shimmer 2.4s linear infinite',
        'fade-in-up': 'fade-in-up 0.4s ease-out both',
      },
    },
  },
  plugins: [],
};
