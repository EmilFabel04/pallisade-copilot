'use client';

import { useState } from 'react';
import { ToolIcon } from '../icons/ToolIcon';

interface WarehouseStepProps {
  onComplete: (data: { pipelineName: string; warehouseType: string }) => void;
  onSkip: () => void;
  onBack: () => void;
  isLoading: boolean;
}

const WAREHOUSES = [
  { id: 'bigquery', name: 'BigQuery' },
  { id: 'snowflake', name: 'Snowflake' },
  { id: 'postgres', name: 'PostgreSQL' },
  { id: 'redshift', name: 'Redshift' },
  { id: 'databricks', name: 'Databricks' },
];

export function WarehouseStep({ onComplete, onSkip, onBack, isLoading }: WarehouseStepProps) {
  const [pipelineName, setPipelineName] = useState('Production Data Stack');
  const [warehouseType, setWarehouseType] = useState('');

  const isValid = pipelineName.trim() && warehouseType;

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-2xl font-bold">Connect Your Warehouse</h2>
        <p className="text-[var(--muted)] mt-2">
          Set up your first data connection to start monitoring
        </p>
      </div>

      <div className="auth-card">
        <div className="space-y-5">
          <div>
            <label className="block text-sm font-medium mb-2">
              Pipeline Name
            </label>
            <input
              type="text"
              value={pipelineName}
              onChange={(e) => setPipelineName(e.target.value)}
              className="auth-input w-full"
              placeholder="e.g., Production Data Stack"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              Warehouse Type
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {WAREHOUSES.map((wh) => (
                <button
                  key={wh.id}
                  type="button"
                  onClick={() => setWarehouseType(wh.id)}
                  className={`p-4 rounded-xl text-center transition-colors border ${
                    warehouseType === wh.id
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                      : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:border-[var(--border-medium)]'
                  }`}
                >
                  <div className="flex justify-center mb-2">
                    <ToolIcon toolType={wh.id} size={32} />
                  </div>
                  <div className="text-sm font-medium text-[var(--text)]">{wh.name}</div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <p className="text-xs text-[var(--muted)] text-center mt-5">
          You&apos;ll configure connection details in the pipeline settings after setup.
        </p>

        <div className="flex gap-3 mt-5">
          <button
            onClick={onBack}
            className="btn w-full justify-center flex-1"
          >
            Back
          </button>
          <button
            onClick={() => onComplete({ pipelineName: pipelineName.trim(), warehouseType })}
            disabled={!isValid || isLoading}
            className="btn btn-elevated w-full justify-center flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? 'Creating...' : 'Continue'}
          </button>
        </div>
      </div>

      <button
        onClick={onSkip}
        className="w-full text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors py-2"
      >
        I&apos;ll do this later
      </button>
    </div>
  );
}
