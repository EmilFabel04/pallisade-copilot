import './globals.css';
import type { ReactNode } from 'react';
import { Toaster } from 'sonner';

export const metadata = {
  title: 'Pallisade — Data Reliability Platform',
  description:
    'Enterprise-grade data reliability platform. Monitor freshness, quality, and schema changes across your data stack with ML-powered anomaly detection.',
  icons: { icon: '/pallisade_emblem.svg' }
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
      </head>
      <body>
        {children}
        <Toaster 
          position="bottom-right" 
          theme="dark"
          toastOptions={{
            style: {
              background: 'rgba(30, 30, 35, 0.95)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              color: '#fff',
            },
          }}
        />
      </body>
    </html>
  );
}
