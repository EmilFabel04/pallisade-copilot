"use client";

/**
 * Fix Test Context
 * 
 * Manages state for fix testing across pages.
 * Allows passing fix data from SmartFixes to Sandbox Lab.
 */

import { createContext, useContext, useState, ReactNode } from "react";

interface FixToTest {
  id: string;
  title: string;
  description: string;
  code: string;
  language: string;
  stack: string;
  confidence: string;
  confidenceScore?: number;
  file_path?: string;
  why?: string;
  
  // Finding context
  findingId?: string;
  findingTitle?: string;
  findingSeverity?: string;
  reportId?: string;
  
  // Table context
  table?: string;
  column?: string;
  
  // Issue context for learning
  issueType?: string;
  issueCategory?: string;
  
  // Metrics at time of issue
  metricsSnapshot?: {
    null_rate?: number;
    freshness_hours?: number;
    row_count?: number;
  };
  
  // Source dialect for sandbox
  sourceDialect?: string;
  
  // Generation method
  generationMethod?: string;
}

interface TestResult {
  status: "passed" | "failed" | "error" | "warning";
  confidenceScore: number;
  durationMs: number;
  validations: Array<{
    name: string;
    passed: boolean;
    message: string;
  }>;
}

interface FixTestContextType {
  // Fix to test
  fixToTest: FixToTest | null;
  setFixToTest: (fix: FixToTest | null) => void;
  
  // Test result
  testResult: TestResult | null;
  setTestResult: (result: TestResult | null) => void;
  
  // Navigation helper
  navigateToSandbox: (fix: FixToTest) => void;
  
  // Clear state
  clearState: () => void;
}

const FixTestContext = createContext<FixTestContextType | undefined>(undefined);

export function FixTestProvider({ children }: { children: ReactNode }) {
  const [fixToTest, setFixToTest] = useState<FixToTest | null>(null);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const navigateToSandbox = (fix: FixToTest) => {
    setFixToTest(fix);
    setTestResult(null);
    // Navigation will be handled by the component using router
  };

  const clearState = () => {
    setFixToTest(null);
    setTestResult(null);
  };

  return (
    <FixTestContext.Provider
      value={{
        fixToTest,
        setFixToTest,
        testResult,
        setTestResult,
        navigateToSandbox,
        clearState,
      }}
    >
      {children}
    </FixTestContext.Provider>
  );
}

export function useFixTest() {
  const context = useContext(FixTestContext);
  if (context === undefined) {
    throw new Error("useFixTest must be used within a FixTestProvider");
  }
  return context;
}

