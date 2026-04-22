import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    // Tree-shake these libs at compile time so dev only bundles what's used.
    // Cuts cold-compile time on heavy pages (dashboard, lineage, assistant)
    // by an order of magnitude.
    optimizePackageImports: [
      'lucide-react',
      'framer-motion',
      '@radix-ui/react-avatar',
      '@radix-ui/react-scroll-area',
      '@radix-ui/react-separator',
      '@radix-ui/react-tooltip',
      '@radix-ui/react-slot',
      'date-fns',
      'recharts',
    ],
  },
};

export default nextConfig;

