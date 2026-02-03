'use client';

import { useState, useRef, useEffect } from 'react';
import { usePipeline } from '@/contexts/PipelineContext';

export function PipelineSelector() {
  const { selectedPipeline, pipelines, loading, selectPipeline, createPipeline } = usePipeline();
  const [isOpen, setIsOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setIsCreating(false);
        setNewName('');
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Focus input when creating
  useEffect(() => {
    if (isCreating && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isCreating]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    
    const created = await createPipeline(newName.trim());
    if (created) {
      setIsCreating(false);
      setNewName('');
      setIsOpen(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleCreate();
    } else if (e.key === 'Escape') {
      setIsCreating(false);
      setNewName('');
    }
  };

  // Status indicator color
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'READY':
      case 'HEALTHY':
        return 'bg-emerald-500';
      case 'WARNING':
      case 'CONFIGURING':
        return 'bg-amber-500';
      case 'ERROR':
        return 'bg-red-500';
      case 'SCANNING':
        return 'bg-blue-500 animate-pulse';
      default:
        return 'bg-white/30';
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.04] animate-pulse">
        <div className="w-2 h-2 rounded-full bg-white/20" />
        <div className="w-24 h-4 bg-white/10 rounded" />
      </div>
    );
  }

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] transition-colors min-w-[160px]"
      >
        {selectedPipeline ? (
          <>
            <span 
              className={`w-2 h-2 rounded-full ${getStatusColor(selectedPipeline.status)}`} 
              title={selectedPipeline.status}
            />
            <span className="text-[13px] text-white/90 truncate max-w-[120px]">
              {selectedPipeline.name}
            </span>
          </>
        ) : (
          <>
            <span className="w-2 h-2 rounded-full bg-white/30" />
            <span className="text-[13px] text-white/50">No pipeline</span>
          </>
        )}
        <svg 
          className={`w-4 h-4 text-white/40 ml-auto transition-transform ${isOpen ? 'rotate-180' : ''}`} 
          fill="none" 
          stroke="currentColor" 
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute left-0 top-full mt-1 w-64 py-1 rounded-lg bg-[#0a0a0a] border border-white/[0.08] shadow-xl z-50">
          {/* Header */}
          <div className="px-3 py-2 border-b border-white/[0.06]">
            <p className="text-[11px] font-medium text-white/40 uppercase tracking-wider">
              Pipeline Configurations
            </p>
          </div>

          {/* Pipeline List */}
          <div className="max-h-64 overflow-y-auto py-1">
            {pipelines.length === 0 ? (
              <div className="px-3 py-4 text-center">
                <p className="text-[13px] text-white/40">No pipelines yet</p>
                <p className="text-[11px] text-white/30 mt-1">Create one to get started</p>
              </div>
            ) : (
              pipelines.map((pipeline) => (
                <button
                  key={pipeline.id}
                  onClick={() => {
                    selectPipeline(pipeline.id);
                    setIsOpen(false);
                  }}
                  className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-white/[0.04] transition-colors ${
                    selectedPipeline?.id === pipeline.id ? 'bg-white/[0.06]' : ''
                  }`}
                >
                  <span 
                    className={`w-2 h-2 rounded-full flex-shrink-0 ${getStatusColor(pipeline.status)}`}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] text-white/90 truncate">{pipeline.name}</p>
                    {pipeline.description && (
                      <p className="text-[11px] text-white/40 truncate">{pipeline.description}</p>
                    )}
                  </div>
                  {selectedPipeline?.id === pipeline.id && (
                    <svg className="w-4 h-4 text-[var(--accent)] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </button>
              ))
            )}
          </div>

          {/* Create New */}
          <div className="border-t border-white/[0.06] pt-1 mt-1">
            {isCreating ? (
              <div className="px-3 py-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Pipeline name..."
                  className="w-full px-2 py-1.5 text-[13px] bg-white/[0.06] border border-white/[0.08] rounded text-white placeholder-white/40 outline-none focus:border-[var(--accent)]/50"
                />
                <div className="flex gap-2 mt-2">
                  <button
                    onClick={handleCreate}
                    disabled={!newName.trim()}
                    className="flex-1 px-2 py-1 text-[12px] font-medium bg-[var(--accent)] text-white rounded hover:bg-[var(--accent)]/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    Create
                  </button>
                  <button
                    onClick={() => {
                      setIsCreating(false);
                      setNewName('');
                    }}
                    className="px-2 py-1 text-[12px] text-white/60 hover:text-white transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setIsCreating(true)}
                className="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-white/60 hover:text-white hover:bg-white/[0.04] transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                New Pipeline
              </button>
            )}
          </div>

          {/* Settings Links */}
          <div className="border-t border-white/[0.06] pt-1 mt-1">
            {selectedPipeline && (
              <a
                href="/dashboard/pipeline/settings"
                className="flex items-center gap-2 px-3 py-2 text-[13px] text-white/50 hover:text-white hover:bg-white/[0.04] transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.204-.107-.397.165-.71.505-.78.929l-.15.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.505-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.107-1.204l-.527-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Pipeline Settings
              </a>
            )}
            <a
              href="/dashboard/pipeline"
              className="flex items-center gap-2 px-3 py-2 text-[13px] text-white/50 hover:text-white hover:bg-white/[0.04] transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
              </svg>
              Visual Editor
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
