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
import { ClarificationProvider } from "@/components/clarifications/ClarificationProvider";
import { ClarificationPopup } from "@/components/clarifications/ClarificationPopup";

interface DashboardProvidersProps {
  children: ReactNode;
}

export function DashboardProviders({ children }: DashboardProvidersProps) {
  return (
    <PipelineProvider>
      <ClarificationProvider>
        <FixTestProvider>
          <TeamBootstrapper />
          {children}
          <ClarificationPopup />
        </FixTestProvider>
      </ClarificationProvider>
    </PipelineProvider>
  );
}

