'use client';

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';

interface PipelineStack {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  healthScore?: number | null;
  nodeCount?: number;
  lastScanAt?: string | null;
}

interface PipelineContextType {
  // Current selected pipeline
  selectedPipeline: PipelineStack | null;
  selectedPipelineId: string | null;
  
  // All available pipelines
  pipelines: PipelineStack[];
  
  // Loading states
  loading: boolean;
  error: string | null;
  
  // Actions
  selectPipeline: (pipelineId: string | null) => void;
  refreshPipelines: () => Promise<void>;
  createPipeline: (name: string, description?: string) => Promise<PipelineStack | null>;
}

const PipelineContext = createContext<PipelineContextType | undefined>(undefined);

const STORAGE_KEY = 'pallisade-selected-pipeline';

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [pipelines, setPipelines] = useState<PipelineStack[]>([]);
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  // Get the full selected pipeline object
  const selectedPipeline = pipelines.find(p => p.id === selectedPipelineId) || null;

  // Fetch all pipeline stacks
  const refreshPipelines = useCallback(async () => {
    try {
      setError(null);
      const res = await fetch('/api/pipeline');

      if (!res.ok) {
        // Handle specific error codes gracefully without throwing
        if (res.status === 401) {
          setError('Please sign in to view pipelines');
          setPipelines([]);
          return [];
        }
        const errorData = await res.json().catch(() => ({}));
        setError(errorData.error || 'Failed to load pipelines');
        setPipelines([]);
        return [];
      }

      const data = await res.json();
      const stackList = data.stacks || [];
      setPipelines(stackList);

      // If current selection is invalid, select the first available
      if (stackList.length > 0) {
        const currentStillValid = selectedPipelineId && stackList.some((s: PipelineStack) => s.id === selectedPipelineId);
        if (!currentStillValid) {
          // Check localStorage for saved selection
          const saved = localStorage.getItem(STORAGE_KEY);
          const savedValid = saved && stackList.some((s: PipelineStack) => s.id === saved);

          if (savedValid) {
            setSelectedPipelineId(saved);
          } else {
            // Default to first pipeline
            setSelectedPipelineId(stackList[0].id);
            localStorage.setItem(STORAGE_KEY, stackList[0].id);
          }
        }
      } else {
        setSelectedPipelineId(null);
      }

      return stackList;
    } catch (err) {
      console.error('Failed to fetch pipelines:', err);
      setError('Failed to load pipelines. Check your connection and try again.');
      setPipelines([]);
      return [];
    }
  }, [selectedPipelineId]);

  // Load pipelines on mount
  useEffect(() => {
    const init = async () => {
      // Load saved selection from localStorage
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        setSelectedPipelineId(saved);
      }
      
      setMounted(true);
      await refreshPipelines();
      setLoading(false);
    };
    
    init();
  }, []);

  // Select a pipeline
  const selectPipeline = useCallback((pipelineId: string | null) => {
    setSelectedPipelineId(pipelineId);
    
    if (pipelineId) {
      localStorage.setItem(STORAGE_KEY, pipelineId);
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  // Create a new pipeline
  const createPipeline = useCallback(async (name: string, description?: string): Promise<PipelineStack | null> => {
    try {
      const res = await fetch('/api/pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description }),
      });
      
      if (!res.ok) {
        throw new Error('Failed to create pipeline');
      }
      
      const data = await res.json();
      const newPipeline = data.stack;
      
      // Refresh the list and select the new pipeline
      await refreshPipelines();
      selectPipeline(newPipeline.id);
      
      return newPipeline;
    } catch (err) {
      console.error('Failed to create pipeline:', err);
      setError('Failed to create pipeline');
      return null;
    }
  }, [refreshPipelines, selectPipeline]);

  // Don't render until mounted to avoid hydration issues
  if (!mounted) {
    return (
      <PipelineContext.Provider
        value={{
          selectedPipeline: null,
          selectedPipelineId: null,
          pipelines: [],
          loading: true,
          error: null,
          selectPipeline: () => {},
          refreshPipelines: async () => {},
          createPipeline: async () => null,
        }}
      >
        {children}
      </PipelineContext.Provider>
    );
  }

  return (
    <PipelineContext.Provider
      value={{
        selectedPipeline,
        selectedPipelineId,
        pipelines,
        loading,
        error,
        selectPipeline,
        refreshPipelines,
        createPipeline,
      }}
    >
      {children}
    </PipelineContext.Provider>
  );
}

export function usePipeline() {
  const context = useContext(PipelineContext);
  if (context === undefined) {
    throw new Error('usePipeline must be used within a PipelineProvider');
  }
  return context;
}

// Hook to get just the selected pipeline ID (useful for API calls)
export function useSelectedPipelineId() {
  const { selectedPipelineId } = usePipeline();
  return selectedPipelineId;
}
