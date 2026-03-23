'use client';

import { useState } from 'react';
import { Button } from '../ui/button';

interface WarehouseStepProps {
  onComplete: (data: { pipelineName: string; warehouseType: string }) => void;
  onSkip: () => void;
  onBack: () => void;
  isLoading: boolean;
}

const WAREHOUSES = [
  { id: 'BIGQUERY', name: 'BigQuery', icon: 'BQ' },
  { id: 'SNOWFLAKE', name: 'Snowflake', icon: 'SF' },
  { id: 'POSTGRES', name: 'PostgreSQL', icon: 'PG' },
  { id: 'REDSHIFT', name: 'Redshift', icon: 'RS' },
  { id: 'DATABRICKS', name: 'Databricks', icon: 'DB' },
];

export function WarehouseStep({ onComplete, onSkip, onBack, isLoading }: WarehouseStepProps) {
  const [pipelineName, setPipelineName] = useState('Production Data Stack');
  const [warehouseType, setWarehouseType] = useState('');

  const isValid = pipelineName.trim() && warehouseType;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[var(--text)]">Connect Your Warehouse</h2>
        <p className="text-[var(--muted)] mt-1">
          Set up your first data connection to start monitoring
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Pipeline Name
          </label>
          <input
            type="text"
            value={pipelineName}
            onChange={(e) => setPipelineName(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            placeholder="e.g., Production Data Stack"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
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
                    ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                    : 'bg-[var(--surface-sunken)] text-[var(--text)] border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                }`}
              >
                <div className="text-lg font-bold mb-1">{wh.icon}</div>
                <div className="text-sm font-medium">{wh.name}</div>
              </button>
            ))}
          </div>
        </div>
      </div>

      <p className="text-xs text-[var(--muted)] text-center">
        You'll configure connection details in the pipeline settings after setup.
      </p>

      <div className="flex gap-3">
        <Button onClick={onBack} variant="secondary" size="lg" className="flex-1">
          Back
        </Button>
        <Button
          onClick={() => onComplete({ pipelineName: pipelineName.trim(), warehouseType })}
          disabled={!isValid || isLoading}
          size="lg"
          className="flex-1"
        >
          {isLoading ? 'Creating...' : 'Continue'}
        </Button>
      </div>

      <button
        onClick={onSkip}
        className="w-full text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors py-2"
      >
        I'll do this later
      </button>
    </div>
  );
}
