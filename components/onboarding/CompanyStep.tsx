'use client';

import { useState } from 'react';

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
    <div>
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold">Your Company</h2>
        <p className="text-[var(--muted)] mt-2">Help us understand your organization</p>
      </div>

      <div className="auth-card">
        <div className="space-y-5">
          <div>
            <label className="block text-sm font-medium mb-2">
              Company Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="auth-input"
              placeholder="Company name"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
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
                      : 'bg-[var(--overlay-bg)] text-[var(--text)] border border-[var(--subtle-border)] hover:border-[var(--border-medium)]'
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              Industry <span className="text-[var(--muted)]">(optional)</span>
            </label>
            <select
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              className="auth-input"
            >
              <option value="">Select industry</option>
              {INDUSTRIES.map((i) => (
                <option key={i} value={i}>{i}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
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
                      : 'bg-[var(--overlay-bg)] text-[var(--text)] border border-[var(--subtle-border)] hover:border-[var(--border-medium)]'
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-3 pt-1">
            <button
              onClick={onBack}
              className="btn w-full justify-center"
            >
              Back
            </button>
            <button
              onClick={() =>
                onComplete({
                  name: name.trim(),
                  companySize,
                  industry: industry || undefined,
                  dataTeamSize: dataTeamSize || undefined,
                })
              }
              disabled={!isValid || isLoading}
              className="btn btn-elevated w-full justify-center"
            >
              {isLoading ? 'Saving...' : 'Continue'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
