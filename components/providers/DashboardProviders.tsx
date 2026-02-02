"use client";

/**
 * Dashboard Providers
 * 
 * Client-side providers for dashboard functionality.
 */

import { ReactNode } from "react";
import { FixTestProvider } from "@/components/dashboard/FixTestContext";
import { TeamBootstrapper } from "./TeamBootstrapper";
import { PipelineProvider } from "@/contexts/PipelineContext";

interface DashboardProvidersProps {
  children: ReactNode;
}

export function DashboardProviders({ children }: DashboardProvidersProps) {
  return (
    <PipelineProvider>
      <FixTestProvider>
        <TeamBootstrapper />
        {children}
      </FixTestProvider>
    </PipelineProvider>
  );
}

