"use client";

/**
 * Dashboard Providers
 * 
 * Client-side providers for dashboard functionality.
 */

import { ReactNode } from "react";
import { FixTestProvider } from "@/components/dashboard/FixTestContext";
import { TeamBootstrapper } from "./TeamBootstrapper";

interface DashboardProvidersProps {
  children: ReactNode;
}

export function DashboardProviders({ children }: DashboardProvidersProps) {
  return (
    <FixTestProvider>
      <TeamBootstrapper />
      {children}
    </FixTestProvider>
  );
}

