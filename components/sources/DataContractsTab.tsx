'use client';

import React, { useState } from 'react';
import { Loader2, FileText } from 'lucide-react';
import { useDataContracts, type DataContractSummary } from './useDataContracts';
import { DataContractCard } from './DataContractCard';

interface DataContractsTabProps {
  dataContractsEnabled: boolean;
}

export function DataContractsTab({ dataContractsEnabled }: DataContractsTabProps) {
  const { contracts, loading, error } = useDataContracts();
  const [selectedContract, setSelectedContract] = useState<DataContractSummary | null>(null);

  const groupContracts = contracts.filter(c => !c.isException);
  const exceptionContracts = contracts.filter(c => c.isException);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-12 text-[var(--muted)]">
        Failed to load data contracts
      </div>
    );
  }

  if (contracts.length === 0) {
    return (
      <div className="text-center py-12">
        <FileText className="w-8 h-8 mx-auto mb-3 text-[var(--muted)]" />
        <p className="text-sm text-[var(--muted)]">
          No data contracts yet. Set SLAs on data assets in pipeline overview to auto-generate contracts.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {groupContracts.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide mb-3">
            Group Contracts ({groupContracts.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {groupContracts.map(c => (
              <DataContractCard
                key={c.id}
                contract={c}
                editable={dataContractsEnabled}
                onClick={setSelectedContract}
              />
            ))}
          </div>
        </div>
      )}

      {exceptionContracts.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide mb-3">
            Exception Contracts ({exceptionContracts.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {exceptionContracts.map(c => (
              <DataContractCard
                key={c.id}
                contract={c}
                editable={dataContractsEnabled}
                onClick={setSelectedContract}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
