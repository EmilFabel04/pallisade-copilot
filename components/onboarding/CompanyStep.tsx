'use client';

import { useState } from 'react';
import { Button } from '../ui/button';

interface CompanyStepProps {
  initialName: string;
  onComplete: (data: {
    name: string;
    companySize: string;
    industry?: string;
    dataTeamSize?: string;
  }) => void;
  onBack: () => void;
  isLoading: boolean;
}

const COMPANY_SIZES = ['1-10', '11-50', '51-200', '201-1000', '1000+'];
const INDUSTRIES = ['Fintech', 'Healthcare', 'E-commerce', 'SaaS', 'Media', 'Other'];
const DATA_TEAM_SIZES = ['Just me', '2-5', '6-15', '15+'];

export function CompanyStep({ initialName, onComplete, onBack, isLoading }: CompanyStepProps) {
  const [name, setName] = useState(initialName);
  const [companySize, setCompanySize] = useState('');
  const [industry, setIndustry] = useState('');
  const [dataTeamSize, setDataTeamSize] = useState('');

  const isValid = name.trim() && companySize;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[var(--text)]">Your Company</h2>
        <p className="text-[var(--muted)] mt-1">Help us understand your organization</p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Company Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            placeholder="Company name"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Company Size
          </label>
          <div className="flex flex-wrap gap-2">
            {COMPANY_SIZES.map((size) => (
              <button
                key={size}
                type="button"
                onClick={() => setCompanySize(size)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
                  companySize === size
                    ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                    : 'bg-[var(--surface-sunken)] text-[var(--text)] border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                }`}
              >
                {size}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Industry <span className="text-[var(--muted)]">(optional)</span>
          </label>
          <select
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="w-full px-3 py-2.5 rounded-lg bg-[var(--surface-sunken)] border border-[var(--subtle-border)] text-[var(--text)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
          >
            <option value="">Select industry</option>
            {INDUSTRIES.map((i) => (
              <option key={i} value={i}>{i}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1.5">
            Data Team Size <span className="text-[var(--muted)]">(optional)</span>
          </label>
          <div className="flex flex-wrap gap-2">
            {DATA_TEAM_SIZES.map((size) => (
              <button
                key={size}
                type="button"
                onClick={() => setDataTeamSize(size)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
                  dataTeamSize === size
                    ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                    : 'bg-[var(--surface-sunken)] text-[var(--text)] border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                }`}
              >
                {size}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex gap-3">
        <Button onClick={onBack} variant="secondary" size="lg" className="flex-1">
          Back
        </Button>
        <Button
          onClick={() =>
            onComplete({
              name: name.trim(),
              companySize,
              industry: industry || undefined,
              dataTeamSize: dataTeamSize || undefined,
            })
          }
          disabled={!isValid || isLoading}
          size="lg"
          className="flex-1"
        >
          {isLoading ? 'Saving...' : 'Continue'}
        </Button>
      </div>
    </div>
  );
}
