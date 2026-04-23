'use client';

import { SessionProvider } from 'next-auth/react';

export function OnboardingSessionProvider({ children }: { children: React.ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
