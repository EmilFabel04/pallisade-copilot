'use client';

import { useState, useEffect } from 'react';
import { toast } from 'sonner';

interface Repo {
  id: number;
  name: string;
  fullName: string;
  owner: string;
  ownerAvatar: string;
  isPrivate: boolean;
  description: string | null;
  defaultBranch: string;
}

interface DbtStructure {
  isDbtProject: boolean;
  dbtVersion?: string;
  projectName?: string;
  schemaFiles: string[];
  sourceFiles: string[];
  modelPaths: string[];
  suggestedPaths: {
    freshness: string;
    schema: string;
    sources: string;
  };
}

interface Fix {
  id: string;
  title: string;
  description: string;
  code: string;
  language: string;
  stack_component: string;
  file_path?: string;
  confidence: string;
}

interface ApplyFixModalProps {
  isOpen: boolean;
  onClose: () => void;
  fix: Fix;
  findingTitle?: string;
  findingId?: string;
  reportId?: string;
  table?: string;
}

export function ApplyFixModal({
  isOpen,
  onClose,
  fix,
  findingTitle,
  findingId,
  reportId,
  table,
}: ApplyFixModalProps) {
  const [step, setStep] = useState<'repo' | 'config' | 'applying' | 'success'>('repo');
  const [repos, setRepos] = useState<Repo[]>([]);
  const [loadingRepos, setLoadingRepos] = useState(true);
  const [selectedRepo, setSelectedRepo] = useState<Repo | null>(null);
  const [dbtStructure, setDbtStructure] = useState<DbtStructure | null>(null);
  const [loadingDbt, setLoadingDbt] = useState(false);
  
  // Config form
  const [filePath, setFilePath] = useState(fix.file_path || '');
  const [writeMode, setWriteMode] = useState<'create' | 'append' | 'replace'>('append');
  const [applying, setApplying] = useState(false);
  
  // Result
  const [result, setResult] = useState<{ prUrl: string; prNumber: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch repos on open
  useEffect(() => {
    if (isOpen) {
      fetchRepos();
      setStep('repo');
      setSelectedRepo(null);
      setDbtStructure(null);
      setResult(null);
      setError(null);
    }
  }, [isOpen]);

  // Update file path when dbt structure is detected
  useEffect(() => {
    if (dbtStructure?.isDbtProject) {
      // Suggest appropriate path based on fix type
      if (fix.stack_component === 'dbt') {
        if (fix.id.includes('freshness') || fix.id.includes('source')) {
          setFilePath(dbtStructure.suggestedPaths.sources);
        } else {
          setFilePath(dbtStructure.suggestedPaths.schema);
        }
      }
    }
  }, [dbtStructure, fix]);

  const fetchRepos = async () => {
    setLoadingRepos(true);
    try {
      const res = await fetch('/api/github/repos');
      const data = await res.json();
      
      if (data.error) {
        setError(data.error);
        return;
      }
      
      setRepos(data.repos || []);
    } catch (err: any) {
      setError('Failed to load repositories');
    } finally {
      setLoadingRepos(false);
    }
  };

  const detectDbtStructure = async (owner: string, repo: string) => {
    setLoadingDbt(true);
    try {
      const res = await fetch('/api/github/detect-dbt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ owner, repo }),
      });
      
      const data = await res.json();
      setDbtStructure(data);
    } catch {
      // Not a dbt project or couldn't detect
      setDbtStructure(null);
    } finally {
      setLoadingDbt(false);
    }
  };

  const handleSelectRepo = async (repo: Repo) => {
    setSelectedRepo(repo);
    setFilePath(fix.file_path || '');
    
    // Detect dbt structure if it's a dbt fix
    if (fix.stack_component === 'dbt' || fix.language === 'yaml') {
      await detectDbtStructure(repo.owner, repo.name);
    }
    
    setStep('config');
  };

  const handleApply = async () => {
    if (!selectedRepo) return;
    
    setApplying(true);
    setError(null);
    
    try {
      const res = await fetch('/api/fixes/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fixType: fix.id,
          fixTitle: fix.title,
          fixCode: fix.code,
          language: fix.language,
          owner: selectedRepo.owner,
          repo: selectedRepo.name,
          filePath,
          writeMode,
          reportId,
          findingId,
          findingTitle,
          table,
        }),
      });
      
      const data = await res.json();
      
      if (data.error) {
        setError(data.error);
        return;
      }
      
      setResult({
        prUrl: data.appliedFix.prUrl,
        prNumber: data.appliedFix.prNumber,
      });
      setStep('success');
      toast.success('Pull Request created!');
    } catch (err: any) {
      setError(err.message || 'Failed to apply fix');
    } finally {
      setApplying(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-[var(--card)] rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="p-6 border-b border-[rgba(255,255,255,0.06)]">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold">Apply Fix to Repository</h2>
              <p className="text-sm text-[var(--muted)] mt-1">{fix.title}</p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-[rgba(255,255,255,0.05)] rounded-lg transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          
          {/* Progress steps */}
          <div className="flex items-center gap-2 mt-4">
            {['repo', 'config', 'success'].map((s, i) => (
              <div key={s} className="flex items-center">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                  step === s ? 'bg-[var(--accent)] text-white' :
                  ['repo', 'config', 'success'].indexOf(step) > i ? 'bg-emerald-500/20 text-emerald-400' :
                  'bg-[rgba(255,255,255,0.05)] text-[var(--muted)]'
                }`}>
                  {['repo', 'config', 'success'].indexOf(step) > i ? '✓' : i + 1}
                </div>
                {i < 2 && <div className="w-8 h-0.5 bg-[rgba(255,255,255,0.1)]" />}
              </div>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="p-6">
          {error && (
            <div className="mb-4 p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
              {error}
              {error === 'GitHub not connected' && (
                <a href="/dashboard/pipeline" className="underline ml-2">
                  Connect GitHub →
                </a>
              )}
            </div>
          )}

          {/* Step 1: Select Repository */}
          {step === 'repo' && (
            <div className="space-y-4">
              <div className="text-sm text-[var(--muted)] mb-4">
                Select the repository where you want to apply this fix:
              </div>
              
              {loadingRepos ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
                </div>
              ) : repos.length === 0 ? (
                <div className="text-center py-12">
                  <p className="text-[var(--muted)] mb-4">No repositories with push access found.</p>
                  <a href="/dashboard/pipeline" className="text-[var(--accent-2)] hover:underline">
                    Connect GitHub →
                  </a>
                </div>
              ) : (
                <div className="space-y-2 max-h-[400px] overflow-y-auto">
                  {repos.map((repo) => (
                    <button
                      key={repo.id}
                      onClick={() => handleSelectRepo(repo)}
                      className="w-full p-4 rounded-xl border border-[rgba(255,255,255,0.06)] hover:border-[var(--accent)]/50 hover:bg-[rgba(255,255,255,0.02)] transition-all text-left flex items-center gap-4"
                    >
                      <img
                        src={repo.ownerAvatar}
                        alt={repo.owner}
                        className="w-10 h-10 rounded-lg"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{repo.fullName}</span>
                          {repo.isPrivate && (
                            <span className="px-1.5 py-0.5 text-xs rounded bg-amber-500/10 text-amber-400">
                              Private
                            </span>
                          )}
                        </div>
                        {repo.description && (
                          <p className="text-sm text-[var(--muted)] truncate">{repo.description}</p>
                        )}
                      </div>
                      <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Step 2: Configure */}
          {step === 'config' && selectedRepo && (
            <div className="space-y-5">
              {/* Selected repo */}
              <div className="flex items-center gap-3 p-3 rounded-lg bg-[rgba(255,255,255,0.03)]">
                <img
                  src={selectedRepo.ownerAvatar}
                  alt={selectedRepo.owner}
                  className="w-8 h-8 rounded-lg"
                />
                <div className="flex-1">
                  <span className="font-medium">{selectedRepo.fullName}</span>
                </div>
                <button
                  onClick={() => setStep('repo')}
                  className="text-xs text-[var(--accent-2)] hover:underline"
                >
                  Change
                </button>
              </div>

              {/* dbt detection */}
              {loadingDbt ? (
                <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
                  <div className="animate-spin w-4 h-4 border-2 border-[var(--muted)] border-t-transparent rounded-full" />
                  Detecting dbt project structure...
                </div>
              ) : dbtStructure?.isDbtProject ? (
                <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30">
                  <div className="flex items-center gap-2 text-emerald-400 text-sm font-medium">
                    <span>✓</span>
                    dbt project detected
                    {dbtStructure.projectName && (
                      <span className="text-emerald-400/70">({dbtStructure.projectName})</span>
                    )}
                  </div>
                  {dbtStructure.sourceFiles.length > 0 && (
                    <div className="text-xs text-emerald-400/70 mt-1">
                      Found {dbtStructure.sourceFiles.length} source file(s)
                    </div>
                  )}
                </div>
              ) : null}

              {/* File path */}
              <div>
                <label className="block text-sm font-medium mb-2">File Path</label>
                <input
                  type="text"
                  value={filePath}
                  onChange={(e) => setFilePath(e.target.value)}
                  placeholder="models/staging/_sources.yml"
                  className="w-full px-4 py-2.5 rounded-xl bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.06)] focus:border-[var(--accent)] outline-none font-mono text-sm"
                />
                {dbtStructure?.suggestedPaths && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <span className="text-xs text-[var(--muted)]">Suggested:</span>
                    {Object.entries(dbtStructure.suggestedPaths).map(([key, path]) => (
                      <button
                        key={key}
                        onClick={() => setFilePath(path)}
                        className={`text-xs px-2 py-1 rounded ${
                          filePath === path
                            ? 'bg-[var(--accent)]/20 text-[var(--accent-2)]'
                            : 'bg-[rgba(255,255,255,0.05)] text-[var(--muted)] hover:text-white'
                        }`}
                      >
                        {path}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Write mode */}
              <div>
                <label className="block text-sm font-medium mb-2">Write Mode</label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { id: 'create', label: 'Create New', desc: 'Create new file' },
                    { id: 'append', label: 'Append', desc: 'Add to existing file' },
                    { id: 'replace', label: 'Replace', desc: 'Replace file contents' },
                  ].map((mode) => (
                    <button
                      key={mode.id}
                      onClick={() => setWriteMode(mode.id as any)}
                      className={`p-3 rounded-xl border text-left transition-all ${
                        writeMode === mode.id
                          ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                          : 'border-[rgba(255,255,255,0.06)] hover:border-[rgba(255,255,255,0.12)]'
                      }`}
                    >
                      <div className="text-sm font-medium">{mode.label}</div>
                      <div className="text-xs text-[var(--muted)]">{mode.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Code preview */}
              <div>
                <label className="block text-sm font-medium mb-2">Code to Apply</label>
                <pre className="text-xs bg-[rgba(0,0,0,0.4)] p-4 rounded-xl overflow-x-auto max-h-48">
                  <code>{fix.code}</code>
                </pre>
              </div>
            </div>
          )}

          {/* Step 3: Success */}
          {step === 'success' && result && (
            <div className="text-center py-8">
              <div className="w-20 h-20 rounded-full bg-emerald-500/10 flex items-center justify-center mx-auto mb-6">
                <svg className="w-10 h-10 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 className="text-2xl font-bold text-emerald-400 mb-2">Pull Request Created!</h3>
              <p className="text-[var(--muted)] mb-6">
                PR #{result.prNumber} is ready for review
              </p>
              <a
                href={result.prUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-[var(--accent)] hover:bg-[var(--accent-2)] transition-colors font-medium"
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                </svg>
                View on GitHub
              </a>
            </div>
          )}

          {/* Applying state */}
          {step === 'applying' && (
            <div className="text-center py-12">
              <div className="animate-spin w-12 h-12 border-4 border-[var(--accent)] border-t-transparent rounded-full mx-auto mb-4" />
              <p className="text-[var(--muted)]">Creating Pull Request...</p>
            </div>
          )}
        </div>

        {/* Footer */}
        {step === 'config' && (
          <div className="p-6 border-t border-[rgba(255,255,255,0.06)] flex justify-end gap-3">
            <button
              onClick={() => setStep('repo')}
              className="px-4 py-2 text-sm rounded-lg hover:bg-[rgba(255,255,255,0.05)] transition-colors"
            >
              Back
            </button>
            <button
              onClick={handleApply}
              disabled={applying || !filePath}
              className="px-6 py-2 text-sm font-medium rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {applying ? (
                <>
                  <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                  Creating PR...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                  </svg>
                  Create Pull Request
                </>
              )}
            </button>
          </div>
        )}

        {step === 'success' && (
          <div className="p-6 border-t border-[rgba(255,255,255,0.06)] flex justify-center">
            <button
              onClick={onClose}
              className="px-6 py-2 text-sm rounded-lg bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] transition-colors"
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

