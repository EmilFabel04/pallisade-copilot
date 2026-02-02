import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}'
  ],
  theme: {
    extend: {
      colors: {
        background: 'var(--bg)',
        foreground: 'var(--text)',
        accent: 'var(--accent)',
      },
      borderColor: {
        DEFAULT: 'var(--border)',
      },
      boxShadow: {
        accent: '0 8px 24px rgba(139, 11, 16, 0.25)'
      }
    }
  },
  plugins: []
};

export default config;

