'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useRouter } from 'next/navigation';
import { usePipeline } from '@/contexts/PipelineContext';

interface PipelineDetails {
  id: string;
  name: string;
  description: string | null;
  status: string;
  healthScore: number | null;
  tokenLimitMonthly: number | null;
  tokensUsedThisMonth: number;
  tokenResetDate: string;
  createdAt: string;
  updatedAt: string;
  nodeCount: number;
  scanCount: number;
}

interface AccessEntry {
  id: string;
  userId: string;
  accessLevel: 'OWNER' | 'EDITOR' | 'VIEWER';
  tokensUsed: number;
  grantedAt: string;
  user: {
    id: string;
    name: string | null;
    email: string;
    image: string | null;
  } | null;
}

interface AvailableUser {
  id: string;
  name: string | null;
  email: string;
  image: string | null;
  role: string;
}

export default function PipelineSettingsPage() {
  const router = useRouter();
  const { selectedPipelineId, selectedPipeline, refreshPipelines } = usePipeline();
  
  const [pipeline, setPipeline] = useState<PipelineDetails | null>(null);
  const [accessList, setAccessList] = useState<AccessEntry[]>([]);
  const [availableUsers, setAvailableUsers] = useState<AvailableUser[]>([]);
  const [userRole, setUserRole] = useState<string | null>(null);
  const [isOrgAdmin, setIsOrgAdmin] = useState(false);
  
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Form state
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tokenLimit, setTokenLimit] = useState<number | null>(null);
  
  // Delete confirmation
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  
  // Add user modal
  const [showAddUser, setShowAddUser] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [selectedAccessLevel, setSelectedAccessLevel] = useState<'OWNER' | 'EDITOR' | 'VIEWER'>('VIEWER');

  // Fetch pipeline details
  useEffect(() => {
    if (!selectedPipelineId) {
      setLoading(false);
      return;
    }

    const fetchDetails = async () => {
      setLoading(true);
      setError(null);

      try {
        const res = await fetch(`/api/pipeline/${selectedPipelineId}`);
        if (!res.ok) {
          throw new Error('Failed to fetch pipeline details');
        }

        const data = await res.json();
        setPipeline(data.pipeline);
        setUserRole(data.userRole);
        setIsOrgAdmin(data.isOrgAdmin);
        
        // Set form values
        setName(data.pipeline.name);
        setDescription(data.pipeline.description || '');
        setTokenLimit(data.pipeline.tokenLimitMonthly);

        // Fetch access list if admin
        if (data.isOrgAdmin) {
          const accessRes = await fetch(`/api/pipeline/${selectedPipelineId}/access`);
          if (accessRes.ok) {
            const accessData = await accessRes.json();
            setAccessList(accessData.accessList || []);
            setAvailableUsers(accessData.availableUsers || []);
          }
        }
      } catch (err) {
        setError('Failed to load pipeline settings');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchDetails();
  }, [selectedPipelineId]);

  // Save changes
  const handleSave = async () => {
    if (!selectedPipelineId) return;

    setSaving(true);
    setError(null);

    try {
      const res = await fetch(`/api/pipeline/${selectedPipelineId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          description: description || null,
          ...(isOrgAdmin ? { tokenLimitMonthly: tokenLimit } : {}),
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Failed to save');
      }

      // Refresh pipeline list
      await refreshPipelines();
      
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  // Delete pipeline
  const handleDelete = async () => {
    if (!selectedPipelineId || deleteConfirmText !== pipeline?.name) return;

    setSaving(true);
    try {
      const res = await fetch(`/api/pipeline/${selectedPipelineId}`, {
        method: 'DELETE',
      });

      if (!res.ok) {
        throw new Error('Failed to delete pipeline');
      }

      // Refresh and redirect
      await refreshPipelines();
      router.push('/dashboard');
    } catch (err) {
      setError('Failed to delete pipeline');
    } finally {
      setSaving(false);
    }
  };

  // Add user access
  const handleAddUser = async () => {
    if (!selectedPipelineId || !selectedUserId) return;

    try {
      const res = await fetch(`/api/pipeline/${selectedPipelineId}/access`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userId: selectedUserId,
          accessLevel: selectedAccessLevel,
        }),
      });

      if (!res.ok) {
        throw new Error('Failed to add user');
      }

      const data = await res.json();
      setAccessList(prev => [...prev, data.access]);
      setAvailableUsers(prev => prev.filter(u => u.id !== selectedUserId));
      setShowAddUser(false);
      setSelectedUserId('');
    } catch (err) {
      setError('Failed to add user');
    }
  };

  // Remove user access
  const handleRemoveUser = async (userId: string) => {
    if (!selectedPipelineId) return;

    try {
      const res = await fetch(`/api/pipeline/${selectedPipelineId}/access?userId=${userId}`, {
        method: 'DELETE',
      });

      if (!res.ok) {
        throw new Error('Failed to remove user');
      }

      const removedUser = accessList.find(a => a.userId === userId);
      setAccessList(prev => prev.filter(a => a.userId !== userId));
      
      if (removedUser?.user) {
        setAvailableUsers(prev => [...prev, {
          id: removedUser.user!.id,
          name: removedUser.user!.name,
          email: removedUser.user!.email,
          image: removedUser.user!.image,
          role: 'ENGINEER',
        }]);
      }
    } catch (err) {
      setError('Failed to remove user');
    }
  };

  // Update user access level
  const handleUpdateAccess = async (userId: string, newLevel: 'OWNER' | 'EDITOR' | 'VIEWER') => {
    if (!selectedPipelineId) return;

    try {
      const res = await fetch(`/api/pipeline/${selectedPipelineId}/access`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userId,
          accessLevel: newLevel,
        }),
      });

      if (!res.ok) {
        throw new Error('Failed to update access');
      }

      setAccessList(prev => prev.map(a => 
        a.userId === userId ? { ...a, accessLevel: newLevel } : a
      ));
    } catch (err) {
      setError('Failed to update access');
    }
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto py-8 flex items-center justify-center">
        <div className="w-8 h-8 red-spinner" />
      </div>
    );
  }

  if (!selectedPipelineId || !pipeline) {
    return (
      <div className="max-w-4xl mx-auto py-8">
        <div className="text-center py-12">
          <p className="text-[var(--muted)]">No pipeline selected</p>
          <p className="text-sm text-[var(--text-faint)] mt-2">Select a pipeline from the dropdown to view settings</p>
        </div>
      </div>
    );
  }

  const canEdit = userRole === 'OWNER' || userRole === 'EDITOR' || isOrgAdmin;
  const canDelete = userRole === 'OWNER' || isOrgAdmin;

  return (
    <div className="max-w-4xl mx-auto py-8 space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text)]">Pipeline Settings</h1>
          <p className="text-[var(--muted)] mt-1">Configure your data pipeline</p>
        </div>
        <button
          onClick={() => router.push('/dashboard/pipeline')}
          className="px-4 py-2 text-sm text-[var(--text-tertiary)] hover:text-[var(--text)] transition-colors"
        >
          Back to Pipeline
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* General Settings */}
      <div className="bg-[var(--overlay-faint)] border border-[var(--subtle-border)] rounded-xl p-6 space-y-6">
        <h2 className="text-lg font-medium text-[var(--text)]">General</h2>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text-tertiary)] mb-2">Pipeline Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!canEdit}
              className="w-full px-4 py-2.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--accent)]/50 disabled:opacity-50"
              placeholder="My Data Pipeline"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text-tertiary)] mb-2">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={!canEdit}
              rows={3}
              className="w-full px-4 py-2.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--accent)]/50 disabled:opacity-50 resize-none"
              placeholder="Describe this pipeline..."
            />
          </div>

          <div className="flex items-center gap-4 pt-2">
            <div className="text-sm text-[var(--muted)]">
              Status: <span className="text-[var(--text)]">{pipeline.status}</span>
            </div>
            <div className="text-sm text-[var(--muted)]">
              Nodes: <span className="text-[var(--text)]">{pipeline.nodeCount}</span>
            </div>
            <div className="text-sm text-[var(--muted)]">
              Scans: <span className="text-[var(--text)]">{pipeline.scanCount}</span>
            </div>
          </div>
        </div>

        {canEdit && (
          <div className="pt-4 border-t border-[var(--subtle-border)]">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-6 py-2.5 bg-[var(--accent)] hover:bg-[var(--accent)]/90 text-white font-medium rounded-lg transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        )}
      </div>

      {/* Token Usage (Admin Only) */}
      {isOrgAdmin && (
        <div className="bg-[var(--overlay-faint)] border border-[var(--subtle-border)] rounded-xl p-6 space-y-6">
          <h2 className="text-lg font-medium text-[var(--text)]">Token Usage</h2>

          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-[var(--text-tertiary)] mb-2">Monthly Token Limit</label>
              <input
                type="number"
                value={tokenLimit ?? ''}
                onChange={(e) => setTokenLimit(e.target.value ? parseInt(e.target.value) : null)}
                className="w-full px-4 py-2.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--accent)]/50"
                placeholder="Unlimited"
              />
              <p className="text-xs text-[var(--muted)] mt-1">Leave empty for unlimited</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--text-tertiary)] mb-2">Tokens Used This Month</label>
              <div className="px-4 py-2.5 bg-[var(--overlay-faint)] border border-[var(--border-faint)] rounded-lg text-[var(--text)]">
                {pipeline.tokensUsedThisMonth.toLocaleString()}
                {tokenLimit && (
                  <span className="text-[var(--muted)]"> / {tokenLimit.toLocaleString()}</span>
                )}
              </div>
              <p className="text-xs text-[var(--muted)] mt-1">
                Resets: {new Date(pipeline.tokenResetDate).toLocaleDateString()}
              </p>
            </div>
          </div>

          {/* Usage by user */}
          {accessList.length > 0 && (
            <div className="pt-4">
              <h3 className="text-sm font-medium text-[var(--text-tertiary)] mb-3">Usage by User</h3>
              <div className="space-y-2">
                {accessList.map((access) => (
                  <div key={access.id} className="flex items-center justify-between py-2 px-3 bg-[var(--overlay-faint)] rounded-lg">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-[var(--overlay-medium)] flex items-center justify-center text-sm">
                        {access.user?.name?.[0] || access.user?.email?.[0] || '?'}
                      </div>
                      <span className="text-sm text-[var(--text)]">{access.user?.name || access.user?.email}</span>
                    </div>
                    <span className="text-sm text-[var(--muted)]">{access.tokensUsed.toLocaleString()} tokens</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Access Control (Admin Only) */}
      {isOrgAdmin && (
        <div className="bg-[var(--overlay-faint)] border border-[var(--subtle-border)] rounded-xl p-6 space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium text-[var(--text)]">Access Control</h2>
            <button
              onClick={() => setShowAddUser(true)}
              className="px-4 py-2 text-sm bg-[var(--hover-bg)] hover:bg-[var(--overlay-medium)] text-[var(--text)] rounded-lg transition-colors"
            >
              Add User
            </button>
          </div>

          {accessList.length === 0 ? (
            <p className="text-[var(--muted)] text-sm py-4">
              No users have specific access. Organization admins have full access by default.
            </p>
          ) : (
            <div className="space-y-3">
              {accessList.map((access) => (
                <div key={access.id} className="flex items-center justify-between p-4 bg-[var(--overlay-faint)] border border-[var(--border-faint)] rounded-lg">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-full bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center text-white text-sm font-medium">
                      {access.user?.image ? (
                        <img src={access.user.image} alt="" className="w-full h-full rounded-full object-cover" />
                      ) : (
                        access.user?.name?.[0] || access.user?.email?.[0] || '?'
                      )}
                    </div>
                    <div>
                      <p className="text-[var(--text)] font-medium">{access.user?.name || 'Unknown'}</p>
                      <p className="text-sm text-[var(--muted)]">{access.user?.email}</p>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-3">
                    <select
                      value={access.accessLevel}
                      onChange={(e) => handleUpdateAccess(access.userId, e.target.value as any)}
                      className="px-3 py-1.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-sm text-[var(--text)] focus:outline-none"
                    >
                      <option value="VIEWER">Viewer</option>
                      <option value="EDITOR">Editor</option>
                      <option value="OWNER">Owner</option>
                    </select>
                    
                    <button
                      onClick={() => handleRemoveUser(access.userId)}
                      className="p-2 text-[var(--muted)] hover:text-red-400 transition-colors"
                      title="Remove access"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Danger Zone */}
      {canDelete && (
        <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-6 space-y-4">
          <h2 className="text-lg font-medium text-red-400">Danger Zone</h2>
          <p className="text-sm text-[var(--text-tertiary)]">
            Once you delete a pipeline, there is no going back. All data, configurations, and history will be permanently removed.
          </p>
          
          {!showDeleteConfirm ? (
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 rounded-lg transition-colors"
            >
              Delete Pipeline
            </button>
          ) : (
            <div className="space-y-4 p-4 bg-red-500/10 rounded-lg">
              <p className="text-sm text-[var(--text-secondary)]">
                To confirm deletion, type the pipeline name: <strong className="text-[var(--text)]">{pipeline.name}</strong>
              </p>
              <input
                type="text"
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                className="w-full px-4 py-2.5 bg-[var(--overlay-bg)] border border-red-500/30 rounded-lg text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none"
                placeholder="Type pipeline name..."
              />
              <div className="flex gap-3">
                <button
                  onClick={handleDelete}
                  disabled={deleteConfirmText !== pipeline.name || saving}
                  className="px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? 'Deleting...' : 'Delete Pipeline'}
                </button>
                <button
                  onClick={() => {
                    setShowDeleteConfirm(false);
                    setDeleteConfirmText('');
                  }}
                  className="px-4 py-2 text-[var(--text-tertiary)] hover:text-[var(--text)] transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Add User Modal */}
      {showAddUser && createPortal(
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/60" onClick={() => setShowAddUser(false)} />
          <div className="relative bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl p-6 w-full max-w-md space-y-4">
            <h3 className="text-lg font-medium text-[var(--text)]">Add User Access</h3>

            <div>
              <label className="block text-sm font-medium text-[var(--text-tertiary)] mb-2">Select User</label>
              <select
                value={selectedUserId}
                onChange={(e) => setSelectedUserId(e.target.value)}
                className="w-full px-4 py-2.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] focus:outline-none"
              >
                <option value="">Select a user...</option>
                {availableUsers.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.name || user.email} ({user.role})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-[var(--text-tertiary)] mb-2">Access Level</label>
              <select
                value={selectedAccessLevel}
                onChange={(e) => setSelectedAccessLevel(e.target.value as any)}
                className="w-full px-4 py-2.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] focus:outline-none"
              >
                <option value="VIEWER">Viewer - Read-only access</option>
                <option value="EDITOR">Editor - Can modify configuration</option>
                <option value="OWNER">Owner - Full control</option>
              </select>
            </div>

            <div className="flex gap-3 pt-4">
              <button
                onClick={handleAddUser}
                disabled={!selectedUserId}
                className="flex-1 px-4 py-2.5 bg-[var(--accent)] hover:bg-[var(--accent)]/90 text-white font-medium rounded-lg transition-colors disabled:opacity-50"
              >
                Add User
              </button>
              <button
                onClick={() => setShowAddUser(false)}
                className="px-4 py-2.5 text-[var(--text-tertiary)] hover:text-[var(--text)] transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
