'use client';

import { useState, useRef, useEffect, useCallback, Suspense } from 'react';
import { useSession } from 'next-auth/react';
import { usePipeline } from '@/contexts/PipelineContext';
import { ModeSelector, getModeFromSlashCommand } from '@/components/copilot/ModeSelector';
import { MentionDropdown, type MentionItem } from '@/components/copilot/MentionDropdown';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { ChangePlanToolResult, isChangePlanTool, SharePlanModal } from '@/components/copilot/change-plan';
import type { ChangePlan } from '@/types/change-plan';
import { MessageActionMenu, MessageActionButton, SaveArtifactModal } from '@/components/artifacts';
import { OnboardingBanner } from '@/components/copilot';
import { useStreamingChat } from '@/hooks/useStreamingChat';
import { ToolConfirmation } from '@/components/copilot/ToolConfirmation';

type ToolCall = {
  id?: string;
  name: string;
  arguments?: Record<string, unknown>;
  result?: unknown;
};

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
};

type ChatSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  lastMessage?: string;
  pipelineStackId?: string;
};

type SourceNode = {
  id: string;
  name: string;
  toolType: string;
  layer: string;
  status: string;
};

type SourceData = {
  nodes: SourceNode[];
  tables: Array<{ name: string; schema: string; dataset?: string; database?: string }>;
  models: Array<{ name: string; schema: string; materialization: string; description?: string }>;
  connectors: Array<{ name: string; status: string; lastSync?: string }>;
  lastSync?: string;
};

// Thinking steps shown during AI processing
const THINKING_STEPS = [
  'Understanding your question...',
  'Analyzing pipeline context...',
  'Querying data sources...',
  'Formulating response...',
];

// Braille animation frames for streaming pulse
const BRAILLE_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

// Max characters before collapsing user messages
const MAX_MESSAGE_LENGTH = 200;

// Icons as components for cleaner code
const Icons = {
  plus: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
    </svg>
  ),
  menu: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  ),
  trash: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
    </svg>
  ),
  cube: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
    </svg>
  ),
  send: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
    </svg>
  ),
  refresh: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
    </svg>
  ),
  close: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  ),
  table: (
    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
    </svg>
  ),
  copy: (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
    </svg>
  ),
};

function AssistantPageInner() {
  const { data: session } = useSession();
  const { selectedPipelineId, selectedPipeline } = usePipeline();

  // Read deep-link data from sessionStorage (primary) or URL params (fallback).
  // sessionStorage is set by the new RunHistoryTable navigateToScout().
  // URL params are the fallback for when the schedule page hasn't hot-reloaded yet.
  // Using a ref initialized inline — runs synchronously during render, so the
  // data is available before any effects fire. sessionStorage survives React
  // Strict Mode remounts and Suspense re-renders (unlike useSearchParams).
  const deepLinkData = useRef<{ prompt: string; context: string; display: string } | null>(
    typeof window !== 'undefined' ? (() => {
      // Primary: sessionStorage (set by new RunHistoryTable code)
      const json = sessionStorage.getItem('askScoutDeepLink');
      if (json) {
        try { return JSON.parse(json); } catch { /* fall through */ }
      }
      // Fallback: URL params (old code or direct navigation)
      const params = new URLSearchParams(window.location.search);
      const prompt = params.get('prompt');
      if (prompt) {
        const data = {
          prompt,
          context: params.get('context') || '',
          display: params.get('display') || '',
        };
        // Store in sessionStorage so it survives Strict Mode remounts
        sessionStorage.setItem('askScoutDeepLink', JSON.stringify(data));
        // Clean URL immediately — no Next.js re-render
        window.history.replaceState({}, '', '/dashboard/assistant');
        return data;
      }
      return null;
    })() : null
  );

  // Initialize messages with the deep-link user message if present.
  // Because this is a useState lazy initializer, it runs on every mount
  // (including Strict Mode remounts), so the message is always visible.
  const [messages, setMessages] = useState<Message[]>(() => {
    if (!deepLinkData.current) return [];
    return [{
      id: `deeplink-${Date.now()}`,
      role: 'user',
      content: deepLinkData.current.display || deepLinkData.current.prompt,
      timestamp: new Date(),
    }];
  });
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(() => !!deepLinkData.current);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [showHistory, setShowHistory] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(256);
  const [isResizing, setIsResizing] = useState(false);
  const [selectedMode, setSelectedMode] = useState('ask');
  const [selectedModel, setSelectedModel] = useState('gpt-5.2');
  const [thinkingStep, setThinkingStep] = useState(0);
  const [brailleFrame, setBrailleFrame] = useState(0);
  const [showSources, setShowSources] = useState(false);
  const [sourceData, setSourceData] = useState<SourceData>({ nodes: [], tables: [], models: [], connectors: [] });
  const [loadingSources, setLoadingSources] = useState(false);
  const [shareModal, setShareModal] = useState<{
    plan: ChangePlan;
    targetType: 'slack' | 'jira' | 'github_issue';
  } | null>(null);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const [shareToast, setShareToast] = useState<{ message: string; url?: string } | null>(null);
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const [saveArtifactModal, setSaveArtifactModal] = useState<{
    content: string;
    messageId: string;
  } | null>(null);
  const [onboardingStatus, setOnboardingStatus] = useState<string>('NOT_STARTED');
  const [onboardingLoading, setOnboardingLoading] = useState(false);
  const [onboardingCollapsed, setOnboardingCollapsed] = useState(false);
  const [showMentionDropdown, setShowMentionDropdown] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionStartIndex, setMentionStartIndex] = useState<number | null>(null);
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([]);
  const [selectedMentionIndex, setSelectedMentionIndex] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lastPipelineId = useRef<string | null>(null);
  const modelLoadedRef = useRef(false);
  const initialLoadDone = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const promptProcessed = useRef(false);
  const [confirmationLoading, setConfirmationLoading] = useState(false);

  // Streaming chat hook
  const {
    streamingMessage,
    clearStreamingMessage,
    sendMessage: sendStreamingMessage,
    abort: abortStreaming,
  } = useStreamingChat();

  // Sidebar resize constants
  const minSidebarWidth = 200;
  const maxSidebarWidth = 400;

  // Handle sidebar resize
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  // Resize effect - handles mouse move and mouse up
  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = Math.min(maxSidebarWidth, Math.max(minSidebarWidth, e.clientX));
      setSidebarWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      localStorage.setItem('chat-sidebar-width', String(sidebarWidth));
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, sidebarWidth]);

  // Load saved sidebar width
  useEffect(() => {
    const savedWidth = localStorage.getItem('chat-sidebar-width');
    if (savedWidth) {
      const width = parseInt(savedWidth);
      if (!isNaN(width)) {
        setSidebarWidth(Math.min(maxSidebarWidth, Math.max(minSidebarWidth, width)));
      }
    }
  }, []);

  // Load mode and model from localStorage on client
  useEffect(() => {
    if (!modelLoadedRef.current) {
      const savedMode = localStorage.getItem('pallisade-copilot-mode');
      const savedModel = localStorage.getItem('pallisade-copilot-model');
      if (savedMode) setSelectedMode(savedMode);
      if (savedModel) setSelectedModel(savedModel);
      modelLoadedRef.current = true;
    }
  }, []);

  // Persist mode selection to localStorage
  useEffect(() => {
    if (modelLoadedRef.current) {
      localStorage.setItem('pallisade-copilot-mode', selectedMode);
    }
  }, [selectedMode]);

  // Persist model selection to localStorage
  useEffect(() => {
    if (modelLoadedRef.current) {
      localStorage.setItem('pallisade-copilot-model', selectedModel);
    }
  }, [selectedModel]);

  // Fetch sources when pipeline changes (uses cached data)
  useEffect(() => {
    if (selectedPipelineId) fetchSources(selectedPipelineId, false);
  }, [selectedPipelineId]);

  // Build @mention autocomplete items from source data
  useEffect(() => {
    const items: MentionItem[] = [];
    const seen = new Set<string>();

    // Full pipeline reference (always first)
    if (sourceData.nodes.length > 0) {
      items.push({
        label: 'Full Pipeline',
        value: '@pipeline',
        category: 'integration',
        nodeId: '__pipeline__',
        toolType: 'pipeline',
        detail: `${sourceData.nodes.length} integrations`,
      });
    }

    // Integration-level mentions
    for (const node of sourceData.nodes) {
      const val = `@${node.name.replace(/\s+/g, '_')}`;
      if (seen.has(val)) continue;
      seen.add(val);
      items.push({
        label: node.name,
        value: val,
        category: 'integration',
        nodeId: node.id,
        toolType: node.toolType,
        detail: node.layer.toLowerCase(),
      });
    }

    // Table mentions — use full qualified names as labels for clarity
    const warehouseNodes = sourceData.nodes.filter(
      n => ['bigquery', 'snowflake', 'postgres', 'redshift'].includes(n.toolType)
    );
    const defaultWarehouse = warehouseNodes[0];

    for (const table of sourceData.tables) {
      const dataset = table.dataset || table.schema || '';
      const fqn = dataset ? `${dataset}.${table.name}` : table.name;
      const parentNode = warehouseNodes.length === 1
        ? defaultWarehouse
        : warehouseNodes.find(n => n.toolType === (table.database || '').toLowerCase()) || defaultWarehouse;
      const prefix = parentNode?.name.replace(/\s+/g, '_') || 'Warehouse';
      const val = `@${prefix}.${fqn}`;
      if (seen.has(val)) continue;
      seen.add(val);
      items.push({
        label: fqn,
        value: val,
        category: 'table',
        nodeId: parentNode?.id || '',
        toolType: parentNode?.toolType || 'unknown',
        detail: parentNode?.name || 'warehouse',
      });
    }

    // dbt model mentions
    const dbtNode = sourceData.nodes.find(
      n => n.toolType === 'dbt_cloud' || n.toolType === 'dbt_core'
    );
    const dbtPrefix = dbtNode?.name.replace(/\s+/g, '_') || 'dbt';

    for (const model of sourceData.models) {
      const val = `@${dbtPrefix}.${model.name}`;
      if (seen.has(val)) continue;
      seen.add(val);
      items.push({
        label: model.name,
        value: val,
        category: 'model',
        nodeId: dbtNode?.id || '',
        toolType: dbtNode?.toolType || 'dbt_cloud',
        detail: `${model.schema} (${model.materialization})`,
      });
    }

    // Connector mentions (Fivetran, Airbyte connectors)
    const ingestionNode = sourceData.nodes.find(
      n => ['fivetran', 'airbyte', 'stitch'].includes(n.toolType)
    );
    if (ingestionNode) {
      for (const connector of sourceData.connectors) {
        const val = `@${ingestionNode.name.replace(/\s+/g, '_')}.${connector.name.replace(/\s+/g, '_')}`;
        if (seen.has(val)) continue;
        seen.add(val);
        items.push({
          label: connector.name,
          value: val,
          category: 'table',
          nodeId: ingestionNode.id,
          toolType: ingestionNode.toolType,
          detail: `connector (${connector.status})`,
        });
      }
    }

    setMentionItems(items);
  }, [sourceData]);

  // Fetch onboarding status when pipeline changes
  useEffect(() => {
    if (!selectedPipelineId) {
      setOnboardingStatus('NOT_STARTED');
      return;
    }

    // Restore collapsed state from localStorage
    const savedCollapsed = localStorage.getItem(`onboarding-collapsed-${selectedPipelineId}`);
    if (savedCollapsed === 'true') {
      setOnboardingCollapsed(true);
    } else {
      setOnboardingCollapsed(false);
    }

    const fetchOnboardingStatus = async () => {
      try {
        const res = await fetch(`/api/pipeline/${selectedPipelineId}/context`);
        if (res.ok) {
          const data = await res.json();
          const status = data.context?.onboardingStatus || 'NOT_STARTED';
          setOnboardingStatus(status);
          // Force expand when new integration is detected
          if (status === 'NEEDS_UPDATE') {
            setOnboardingCollapsed(false);
            localStorage.removeItem(`onboarding-collapsed-${selectedPipelineId}`);
          }
        }
      } catch (error) {
        console.error('Failed to fetch onboarding status:', error);
      }
    };

    fetchOnboardingStatus();
  }, [selectedPipelineId]);

  // Fetch sources - uses cached data by default, pass refresh=true for fresh discovery
  const fetchSources = async (pipelineId: string, refresh: boolean = false) => {
    setLoadingSources(true);
    try {
      const res = await fetch(`/api/pipeline?id=${pipelineId}`);
      if (!res.ok) return;
      const data = await res.json();
      const stack = data.stack;
      if (!stack?.nodes) return;

      const connectedNodes = stack.nodes.filter((n: any) =>
        n.status === 'CONNECTED' || n.status === 'HEALTHY' || n.status === 'WARNING'
      );
      const allTables: SourceData['tables'] = [];
      const allModels: SourceData['models'] = [];
      const allConnectors: SourceData['connectors'] = [];
      let latestSync: string | undefined;

      await Promise.all(connectedNodes.map(async (node: any) => {
        try {
          const url = `/api/pipeline/${pipelineId}/nodes/${node.id}/tables${refresh ? '?refresh=true' : ''}`;
          const nodeRes = await fetch(url);
          if (!nodeRes.ok) return;
          const nodeData = await nodeRes.json();
          if (nodeData.tables) allTables.push(...nodeData.tables);
          if (nodeData.models) allModels.push(...nodeData.models);
          if (nodeData.connectors) allConnectors.push(...nodeData.connectors);
          if (nodeData.lastSync && (!latestSync || nodeData.lastSync > latestSync)) {
            latestSync = nodeData.lastSync;
          }
        } catch { /* skip failed nodes */ }
      }));

      setSourceData({
        nodes: connectedNodes.map((n: any) => ({
          id: n.id,
          name: n.name,
          toolType: n.toolType,
          layer: n.layer,
          status: n.status,
        })),
        tables: allTables,
        models: allModels,
        connectors: allConnectors,
        lastSync: latestSync,
      });
    } catch (error) {
      console.error('Failed to fetch sources:', error);
    } finally {
      setLoadingSources(false);
    }
  };

  const syncSources = () => {
    if (selectedPipelineId) {
      fetchSources(selectedPipelineId, true);
    }
  };

  const handleStartOnboarding = async () => {
    if (!selectedPipelineId) return;

    setOnboardingLoading(true);
    try {
      // Start onboarding via API
      await fetch(`/api/pipeline/${selectedPipelineId}/context`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'start' }),
      });

      setOnboardingStatus('IN_PROGRESS');

      // Send onboarding message to start the interview
      handleSubmit(
        { preventDefault: () => {} } as React.FormEvent,
        '/onboard Start onboarding - ask me questions about my pipeline setup so you can help me more effectively.'
      );
    } catch (error) {
      console.error('Failed to start onboarding:', error);
    } finally {
      setOnboardingLoading(false);
    }
  };

  // Deep-link effect: send the API message for Ask Scout deep-links.
  // This runs BEFORE the fetchSessions mount effect (effects run in declaration order).
  // The user message is already visible (set via useState initializer above).
  // We only remove from sessionStorage AFTER the API call succeeds, so
  // Strict Mode remounts can re-read the data and re-fire the API call.
  useEffect(() => {
    const data = deepLinkData.current;
    if (!data || promptProcessed.current) return;
    promptProcessed.current = true;

    // Remove from sessionStorage — we've committed to processing
    sessionStorage.removeItem('askScoutDeepLink');

    // Build the full API message with structured context for the LLM
    let apiMessage = data.prompt;
    if (data.context) {
      try {
        const ctx = JSON.parse(data.context);
        const lines: string[] = [
          '--- MONITOR RUN DATA ---',
          `Task: ${ctx.taskName}`,
          `Monitor: ${ctx.monitorType} on ${ctx.targetFqn}`,
          `Status: ${ctx.status}`,
        ];
        if (ctx.value != null) lines.push(`Value: ${ctx.value}`);
        if (ctx.threshold != null) lines.push(`Threshold: ${ctx.threshold}`);
        if (ctx.message) lines.push(`Message: ${ctx.message}`);
        if (ctx.startedAt) lines.push(`Run time: ${ctx.startedAt}`);
        if (ctx.durationMs) lines.push(`Duration: ${ctx.durationMs}ms`);
        if (ctx.details && Object.keys(ctx.details).length > 0) {
          lines.push('', 'Details:');
          for (const [k, v] of Object.entries(ctx.details)) {
            lines.push(`  ${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`);
          }
        }
        if (ctx.sqlExecuted) lines.push('', `SQL: ${ctx.sqlExecuted}`);
        if (ctx.llmValidation) {
          lines.push('', 'AI Assessment:');
          if (ctx.llmValidation.explanation) lines.push(`  Explanation: ${ctx.llmValidation.explanation}`);
          if (ctx.llmValidation.original_status) lines.push(`  Original: ${ctx.llmValidation.original_status}`);
          if (ctx.llmValidation.adjusted_status) lines.push(`  Adjusted: ${ctx.llmValidation.adjusted_status}`);
        }
        lines.push('--- END MONITOR DATA ---', '');
        apiMessage = lines.join('\n') + '\n' + data.prompt;
      } catch { /* invalid context — use prompt as-is */ }
    }

    // Call sendStreamingMessage directly — stable useCallback([]), no stale closure
    sendStreamingMessage(apiMessage, {
      sessionId: undefined,
      pipelineStackId: selectedPipelineId || undefined,
      model: selectedModel,
      mode: 'ask',
    }).then((result) => {
      if (result.sessionId) {
        setSessionId(result.sessionId);
        fetch('/api/copilot/sessions?limit=50')
          .then(res => res.json())
          .then(d => setSessions(d.sessions || []))
          .catch(() => {});
      }
    }).catch((error) => {
      if (error instanceof Error && error.name === 'AbortError') return;
      console.error('Deep-link chat error:', error);
    }).finally(() => {
      setIsLoading(false);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch sessions on mount
  useEffect(() => {
    if (initialLoadDone.current) return;
    initialLoadDone.current = true;
    fetchSessions();
  }, []);

  // Fetch sessions when pipeline changes
  useEffect(() => {
    if (!initialLoadDone.current) return;
    if (lastPipelineId.current === selectedPipelineId) return;
    lastPipelineId.current = selectedPipelineId;
    fetchSessions();
  }, [selectedPipelineId]);

  const fetchSessions = async () => {
    try {
      setLoadingSessions(true);
      const response = await fetch('/api/copilot/sessions?limit=50');
      if (response.ok) {
        const data = await response.json();
        setSessions(data.sessions || []);

        // If deep-link is active (from Ask Scout), don't load any session —
        // the deep-link effect handles everything.
        if (deepLinkData.current || promptProcessed.current) {
          return;
        }

        if (data.sessions && data.sessions.length > 0) {
          const pipelineSession = selectedPipelineId
            ? data.sessions.find((s: ChatSession) => s.pipelineStackId === selectedPipelineId)
            : null;

          if (pipelineSession) {
            loadSession(pipelineSession.id);
          } else {
            loadSession(data.sessions[0].id);
          }
        } else {
          startNewChat();
        }
      }
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
    } finally {
      setLoadingSessions(false);
    }
  };

  const loadSession = async (id: string) => {
    try {
      setIsLoading(true);
      const response = await fetch(`/api/copilot/sessions/${id}`);
      if (response.ok) {
        const data = await response.json();
        setSessionId(data.session.id);
        setMessages(
          data.session.messages.map((m: any) => ({
            id: m.id,
            role: m.role.toLowerCase() as 'user' | 'assistant',
            content: m.content,
            timestamp: new Date(m.createdAt),
            toolCalls: m.toolCalls || undefined,
          }))
        );
      }
    } catch (error) {
      console.error('Failed to load session:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const startNewChat = () => {
    setSessionId(null);
    setMessages([]);
    setInput('');
  };

  const deleteSession = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this chat?')) return;

    try {
      const response = await fetch(`/api/copilot/sessions/${id}`, {
        method: 'DELETE',
      });
      if (response.ok) {
        setSessions(prev => prev.filter(s => s.id !== id));
        if (sessionId === id) {
          startNewChat();
        }
      }
    } catch (error) {
      console.error('Failed to delete session:', error);
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Auto-scroll during streaming
  useEffect(() => {
    if (streamingMessage?.isStreaming) {
      scrollToBottom();
    }
  }, [streamingMessage?.content, streamingMessage?.toolCalls.length]);

  // Cycle through thinking steps while loading
  useEffect(() => {
    if (!isLoading) {
      setThinkingStep(0);
      return;
    }
    const interval = setInterval(() => {
      setThinkingStep(prev => prev + 1);
    }, 2000);
    return () => clearInterval(interval);
  }, [isLoading]);

  // Braille animation frame cycling (fast, smooth rotation)
  useEffect(() => {
    if (!isLoading) {
      setBrailleFrame(0);
      return;
    }
    const interval = setInterval(() => {
      setBrailleFrame(prev => prev + 1);
    }, 80);
    return () => clearInterval(interval);
  }, [isLoading]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  }, [input]);

  const handleSubmit = async (e: React.FormEvent, customMessage?: string) => {
    e.preventDefault();
    let messageText = customMessage || input.trim();
    if (!messageText || isLoading) return;

    let modeToUse = selectedMode;
    const slashCmd = getModeFromSlashCommand(messageText);
    if (slashCmd) {
      modeToUse = slashCmd.mode;
      messageText = slashCmd.message;
      setSelectedMode(slashCmd.mode);
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: customMessage || input.trim(),
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    if (!customMessage) setInput('');
    setIsLoading(true);

    try {
      const { nodeIds: mentionNodeIds, entities: mentionEntities } = parseMentions(messageText);

      const result = await sendStreamingMessage(messageText, {
        sessionId: sessionId || undefined,
        pipelineStackId: selectedPipelineId || undefined,
        model: selectedModel,
        mode: modeToUse,
        nodeIds: mentionNodeIds.length > 0 ? mentionNodeIds : undefined,
        referencedEntities: mentionEntities.length > 0 ? mentionEntities : undefined,
      });

      if (result.sessionId && result.sessionId !== sessionId) {
        setSessionId(result.sessionId);
        const sessionsRes = await fetch('/api/copilot/sessions?limit=50');
        if (sessionsRes.ok) {
          const sessionsData = await sessionsRes.json();
          setSessions(sessionsData.sessions || []);
        }
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('Request aborted by user');
        return;
      }
      console.error('Chat error:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Finalize streaming message into the messages array
  useEffect(() => {
    if (streamingMessage && !streamingMessage.isStreaming && (streamingMessage.content || streamingMessage.toolCalls.length > 0)) {
      // Don't finalize if waiting for confirmation
      if (streamingMessage.pendingConfirmation) return;

      // Map streaming tool calls to frontend format
      const mappedToolCalls: ToolCall[] = streamingMessage.toolCalls.map(tc => {
        const result = (tc.result || {}) as Record<string, any>;
        const flattenedResult = {
          success: result.success,
          error: result.error,
          ...(result.data || {}),
        };
        return {
          id: tc.id,
          name: tc.name,
          arguments: tc.arguments,
          result: flattenedResult,
        };
      });

      const aiMessage: Message = {
        id: streamingMessage.id,
        role: 'assistant',
        content: streamingMessage.content,
        timestamp: new Date(),
        toolCalls: mappedToolCalls,
      };

      setMessages(prev => [...prev, aiMessage]);
      clearStreamingMessage();

      // Handle onboarding tool calls
      if (selectedPipelineId && mappedToolCalls.length > 0) {
        for (const tc of mappedToolCalls) {
          try {
            if (tc.name === 'complete_onboarding' && (tc.result as Record<string, unknown>)?.completed) {
              fetch(`/api/pipeline/${selectedPipelineId}/context`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'complete' }),
              }).then(res => {
                if (res.ok) {
                  setOnboardingStatus('COMPLETED');
                  localStorage.removeItem(`onboarding-collapsed-${selectedPipelineId}`);
                }
              });
            } else if (tc.name === 'save_onboarding_context' && (tc.result as Record<string, unknown>)?.saved) {
              const result = tc.result as Record<string, unknown>;
              fetch(`/api/pipeline/${selectedPipelineId}/context`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  questionKey: result.question_key,
                  answer: result.answer,
                  contextField: result.context_field,
                  integrationTтype: result.integration_type,
                }),
              });
              if (onboardingStatus === 'NOT_STARTED') setOnboardingStatus('IN_PROGRESS');
            }
          } catch (err) {
            console.error(`Failed to persist ${tc.name}:`, err);
          }
        }
      }
    }
  }, [streamingMessage, selectedPipelineId, onboardingStatus, clearStreamingMessage]);

  const handleConfirmTool = async () => {
    if (!streamingMessage?.pendingConfirmation) return;
    setConfirmationLoading(true);

    // Capture pending tool details before clearing streaming message
    const pending = streamingMessage.pendingConfirmation;

    // For apply_change_plan, use the direct endpoint (no LLM round-trip)
    if (pending.toolName === 'apply_change_plan') {
      const planId = pending.arguments?.plan_id as string;
      if (planId) {
        // Finalize partial message WITHOUT the pending apply_change_plan tool call
        // (it would render as a stuck "Executing..." spinner otherwise)
        const partialMessage: Message = {
          id: streamingMessage.id,
          role: 'assistant',
          content: streamingMessage.content,
          timestamp: new Date(),
          toolCalls: streamingMessage.toolCalls
            .filter(tc => tc.name !== 'apply_change_plan' || tc.result != null)
            .map(tc => ({
              id: tc.id,
              name: tc.name,
              arguments: tc.arguments,
              result: tc.result ? { success: tc.result.success, error: tc.result.error, ...(tc.result.data || {}) } : undefined,
            })),
        };
        setMessages(prev => [...prev, partialMessage]);
        clearStreamingMessage();
        setConfirmationLoading(false);
        setIsLoading(false);
        // Pass repo args from the LLM's original tool call if available
        await handleApplyPlan(planId, {
          repoOwner: pending.arguments?.repo_owner as string | undefined,
          repoName: pending.arguments?.repo_name as string | undefined,
          baseBranch: pending.arguments?.base_branch as string | undefined,
        });
        return;
      }
    }

    // Finalize current streaming message (partial) into messages
    const partialMessage: Message = {
      id: streamingMessage.id,
      role: 'assistant',
      content: streamingMessage.content,
      timestamp: new Date(),
      toolCalls: streamingMessage.toolCalls.map(tc => ({
        id: tc.id,
        name: tc.name,
        arguments: tc.arguments,
        result: tc.result ? { success: tc.result.success, error: tc.result.error, ...(tc.result.data || {}) } : undefined,
      })),
    };
    setMessages(prev => [...prev, partialMessage]);
    clearStreamingMessage();

    // For all other tools, re-send with the pending tool call details
    try {
      await sendStreamingMessage(
        `[SYSTEM] User confirmed execution of tool ${pending.toolName}. Execute it now.`,
        {
          sessionId: sessionId || undefined,
          pipelineStackId: selectedPipelineId || undefined,
          model: selectedModel,
          mode: selectedMode,
          confirmedToolIds: [pending.toolName],
          pendingToolCall: {
            toolUseId: pending.toolUseId,
            toolName: pending.toolName,
            arguments: pending.arguments,
          },
        },
      );
    } catch (err) {
      console.error('Confirm tool error:', err);
    } finally {
      setConfirmationLoading(false);
      setIsLoading(false);
    }
  };

  const handleDenyTool = async () => {
    if (!streamingMessage?.pendingConfirmation) return;
    const toolName = streamingMessage.pendingConfirmation.toolName;

    // Finalize partial message
    const partialMessage: Message = {
      id: streamingMessage.id,
      role: 'assistant',
      content: streamingMessage.content,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, partialMessage]);
    clearStreamingMessage();

    // Send denial as new user message
    handleSubmit(
      { preventDefault: () => {} } as React.FormEvent,
      `I declined to execute ${toolName}. Please explain what would have happened and suggest alternatives.`,
    );
  };

  // "Create PR" — direct call, no LLM round-trip
  const [applyingPlanId, setApplyingPlanId] = useState<string | null>(null);

  const handleApplyPlan = async (
    planId: string,
    repoArgs?: { repoOwner?: string; repoName?: string; baseBranch?: string },
  ) => {
    if (applyingPlanId) return;
    setApplyingPlanId(planId);

    try {
      const res = await fetch('/api/copilot/apply-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_id: planId,
          repo_owner: repoArgs?.repoOwner,
          repo_name: repoArgs?.repoName,
          base_branch: repoArgs?.baseBranch,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        // Show error as an assistant message
        setMessages(prev => [...prev, {
          id: `apply_err_${Date.now()}`,
          role: 'assistant',
          content: `Failed to create PR: ${data.error || 'Unknown error'}`,
          timestamp: new Date(),
        }]);
        return;
      }

      // Success — add a message with the PR link and auto-open
      const prUrl = data.pr_url;
      setMessages(prev => [...prev, {
        id: `apply_ok_${Date.now()}`,
        role: 'assistant',
        content: `Pull Request created: [#${data.pr_number} — ${data.branch}](${prUrl})\n\n${data.files_changed || 0} file(s) changed.`,
        timestamp: new Date(),
      }]);

      if (prUrl) {
        window.open(prUrl, '_blank', 'noopener,noreferrer');
      }
    } catch (err: any) {
      console.error('Apply plan error:', err);
      setMessages(prev => [...prev, {
        id: `apply_err_${Date.now()}`,
        role: 'assistant',
        content: `Failed to create PR: ${err.message || 'Network error'}`,
        timestamp: new Date(),
      }]);
    } finally {
      setApplyingPlanId(null);
    }
  };

  const handleStop = () => {
    abortStreaming();
    setIsLoading(false);
  };

  // @mention helpers
  const getFilteredMentionItems = useCallback((): MentionItem[] => {
    if (!mentionQuery) return mentionItems.slice(0, 12);
    const q = mentionQuery.toLowerCase();
    return mentionItems.filter(item =>
      item.label.toLowerCase().includes(q) ||
      item.value.toLowerCase().includes(q) ||
      (item.detail && item.detail.toLowerCase().includes(q))
    ).slice(0, 12);
  }, [mentionQuery, mentionItems]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    const cursorPos = e.target.selectionStart || 0;
    setInput(value);

    // Detect @mention trigger
    const textBeforeCursor = value.slice(0, cursorPos);
    const atIndex = textBeforeCursor.lastIndexOf('@');

    if (atIndex >= 0) {
      const charBefore = atIndex > 0 ? value[atIndex - 1] : ' ';
      if (charBefore === ' ' || charBefore === '\n' || atIndex === 0) {
        const query = textBeforeCursor.slice(atIndex + 1);
        if (!query.includes(' ')) {
          setShowMentionDropdown(true);
          setMentionQuery(query);
          setMentionStartIndex(atIndex);
          setSelectedMentionIndex(0);
          return;
        }
      }
    }

    setShowMentionDropdown(false);
    setMentionQuery('');
    setMentionStartIndex(null);
  };

  const handleMentionSelect = (item: MentionItem) => {
    if (mentionStartIndex === null) return;
    const cursorPos = textareaRef.current?.selectionStart || input.length;
    const before = input.slice(0, mentionStartIndex);
    const after = input.slice(cursorPos);
    const newValue = `${before}${item.value} ${after}`;
    setInput(newValue);
    setShowMentionDropdown(false);
    setMentionQuery('');
    setMentionStartIndex(null);

    setTimeout(() => {
      if (textareaRef.current) {
        const newCursorPos = mentionStartIndex + item.value.length + 1;
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(newCursorPos, newCursorPos);
      }
    }, 0);
  };

  const parseMentions = (text: string): { nodeIds: string[]; entities: string[] } => {
    const mentionRegex = /@(\S+)/g;
    const nodeIds = new Set<string>();
    const entities: string[] = [];
    let match;

    while ((match = mentionRegex.exec(text)) !== null) {
      const mentionValue = `@${match[1]}`;

      // @pipeline → include all node IDs + "pipeline" entity
      if (mentionValue === '@pipeline') {
        for (const node of sourceData.nodes) {
          nodeIds.add(node.id);
        }
        entities.push('pipeline');
        continue;
      }

      const item = mentionItems.find(m => m.value === mentionValue);
      if (item) {
        if (item.nodeId) nodeIds.add(item.nodeId);
        if (item.category === 'table' || item.category === 'model') {
          entities.push(match[1]); // Without @ prefix
        } else {
          entities.push(match[1]); // Integration name too
        }
      }
    }

    return { nodeIds: Array.from(nodeIds), entities };
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showMentionDropdown) {
      const filtered = getFilteredMentionItems();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedMentionIndex(prev => Math.min(prev + 1, filtered.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedMentionIndex(prev => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        if (filtered.length > 0) {
          e.preventDefault();
          handleMentionSelect(filtered[selectedMentionIndex]);
          return;
        }
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setShowMentionDropdown(false);
        return;
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    return date.toLocaleDateString();
  };

  return (
    <TooltipProvider>
      <div className="h-[calc(100vh-120px)] flex">
        {/* Chat History Sidebar */}
        <div
          className={cn(
            'flex-shrink-0 overflow-hidden relative',
            !showHistory && 'w-0',
            isResizing ? '' : 'transition-[width] duration-200'
          )}
          style={{ width: showHistory ? sidebarWidth : 0 }}
        >
          <div
            className="h-full flex flex-col border-r border-white/[0.06] px-3"
            style={{ width: sidebarWidth }}
          >
            {/* New Chat Button */}
            <Button onClick={startNewChat} className="mb-4 gap-2">
              {Icons.plus}
              <span>New Chat</span>
            </Button>

            {/* Sessions List */}
            <ScrollArea className="flex-1">
              <div className="space-y-1">
                {loadingSessions ? (
                  <div className="flex items-center justify-center py-8">
                    <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                  </div>
                ) : sessions.length === 0 ? (
                  <div className="text-center py-8 text-sm text-[var(--muted)]">
                    No chat history yet
                  </div>
                ) : (
                  sessions.map((s) => (
                    <div
                      key={s.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => loadSession(s.id)}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') loadSession(s.id); }}
                      className={cn(
                        'w-full text-left px-2.5 py-2 rounded-lg transition-all group cursor-pointer',
                        sessionId === s.id
                          ? 'bg-white/[0.08] text-white'
                          : 'hover:bg-white/[0.04] text-[var(--muted)] hover:text-white'
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium truncate leading-tight">{s.title}</div>
                          <div className="text-[10px] opacity-50 mt-0.5">{formatDate(s.updatedAt)}</div>
                        </div>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              onClick={(e) => deleteSession(s.id, e)}
                              className="p-1 flex-shrink-0 opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-red-400 transition-all rounded"
                            >
                              {Icons.trash}
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>Delete chat</TooltipContent>
                        </Tooltip>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </ScrollArea>
          </div>

          {/* Resize Handle */}
          {showHistory && (
            <div
              className={cn(
                "absolute right-0 top-0 bottom-0 w-1.5 cursor-col-resize z-10 transition-colors",
                isResizing ? "bg-violet-500" : "hover:bg-violet-500/50"
              )}
              onMouseDown={handleResizeStart}
            />
          )}
        </div>

        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Compact Header */}
          <div className="flex items-center justify-between py-2 px-4 border-b border-white/[0.06]">
            <div className="flex items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowHistory(!showHistory)}
                    className="p-1.5 h-8 w-8"
                  >
                    {Icons.menu}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{showHistory ? 'Hide history' : 'Show history'}</TooltipContent>
              </Tooltip>
              <Avatar className="w-7 h-7">
                <AvatarImage src="/pallisade_scout.svg" alt="Scout" />
                <AvatarFallback className="text-xs">AI</AvatarFallback>
              </Avatar>
              <h1 className="text-sm font-semibold">Pallisade Scout</h1>
            </div>

            {/* Sources */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowSources(!showSources)}
              className={cn(
                'gap-1.5 px-2.5 h-8 text-xs',
                showSources && 'bg-white/[0.08]'
              )}
            >
              {Icons.cube}
              <span>Sources</span>
              {sourceData.nodes.length > 0 && (
                <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-emerald-500/20 text-emerald-400">
                  {sourceData.nodes.length}
                </span>
              )}
            </Button>
          </div>

          {/* Onboarding Banner */}
          {selectedPipelineId && onboardingStatus !== 'COMPLETED' && (
            <div className="px-4 pt-3">
              <OnboardingBanner
                status={onboardingStatus as 'NOT_STARTED' | 'IN_PROGRESS' | 'NEEDS_UPDATE'}
                onStart={handleStartOnboarding}
                isLoading={onboardingLoading}
                collapsed={onboardingCollapsed}
                onToggleCollapse={() => {
                  const next = !onboardingCollapsed;
                  setOnboardingCollapsed(next);
                  if (selectedPipelineId) {
                    if (next) {
                      localStorage.setItem(`onboarding-collapsed-${selectedPipelineId}`, 'true');
                    } else {
                      localStorage.removeItem(`onboarding-collapsed-${selectedPipelineId}`);
                    }
                  }
                }}
              />
            </div>
          )}

          {/* Messages */}
          <ScrollArea className="flex-1 px-4 py-3">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center px-4">
                <Avatar className="w-14 h-14 mb-3">
                  <AvatarImage src="/pallisade_scout.svg" alt="Scout" />
                  <AvatarFallback className="text-xl">AI</AvatarFallback>
                </Avatar>
                <h2 className="text-base font-semibold mb-1">How can I help?</h2>
                <p className="text-xs text-[var(--muted)] max-w-sm mb-4">
                  Query your warehouse, explore lineage, debug pipelines.
                </p>

                {/* Quick prompts */}
                <div className="flex flex-wrap gap-1.5 justify-center max-w-lg">
                  {[
                    "How many rows are in my tables?",
                    "What's the freshness of my data?",
                    "Show pipeline dependencies",
                  ].map((prompt, i) => (
                    <Button
                      key={i}
                      variant="ghost"
                      size="sm"
                      onClick={() => handleSubmit({ preventDefault: () => {} } as React.FormEvent, prompt)}
                      className="text-xs text-[var(--muted)] hover:text-white h-7 px-2.5"
                    >
                      {prompt}
                    </Button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-3 pb-2">
                {messages.map((message) => (
                  <div key={message.id} className={cn('flex gap-2 min-w-0', message.role === 'user' && 'justify-end')}>
                    {message.role === 'assistant' && (
                      <Avatar className="w-6 h-6 flex-shrink-0 mt-0.5">
                        <AvatarImage src="/pallisade_scout.svg" alt="AI" />
                        <AvatarFallback className="text-[10px]">AI</AvatarFallback>
                      </Avatar>
                    )}
                    <div className={cn(
                      'max-w-[85%] min-w-0',
                      message.role === 'user' ? '' : 'space-y-2'
                    )}>
                      {message.role === 'assistant' ? (
                        <div className="relative group min-w-0">
                          <div className="px-1 py-1">
                            <MessageContent content={message.content} />
                          </div>
                          {/* Three-dot menu button */}
                          <div className="absolute top-0 right-0 opacity-0 group-hover:opacity-100 transition-opacity">
                            <MessageActionButton
                              onClick={() => setActiveMenuId(activeMenuId === message.id ? null : message.id)}
                            />
                            <MessageActionMenu
                              content={message.content}
                              messageId={message.id}
                              sessionId={sessionId}
                              isOpen={activeMenuId === message.id}
                              onClose={() => setActiveMenuId(null)}
                              onSaveToArtifacts={() => {
                                setSaveArtifactModal({ content: message.content, messageId: message.id });
                                setActiveMenuId(null);
                              }}
                            />
                          </div>
                        </div>
                      ) : (
                        <div className="px-3 py-2 bg-white/[0.06] border border-[var(--accent)]/50 text-white rounded-xl rounded-tr-sm">
                          {message.content.length > MAX_MESSAGE_LENGTH ? (
                            <div>
                              <div className="text-sm whitespace-pre-wrap break-words">
                                {expandedMessages.has(message.id)
                                  ? message.content
                                  : message.content.slice(0, MAX_MESSAGE_LENGTH) + '...'}
                              </div>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setExpandedMessages(prev => {
                                    const next = new Set(prev);
                                    if (next.has(message.id)) {
                                      next.delete(message.id);
                                    } else {
                                      next.add(message.id);
                                    }
                                    return next;
                                  });
                                }}
                                className="text-xs opacity-70 hover:opacity-100 mt-1.5 underline"
                              >
                                {expandedMessages.has(message.id) ? 'Show less' : 'Show more'}
                              </button>
                            </div>
                          ) : (
                            <MessageContent content={message.content} />
                          )}
                        </div>
                      )}
                      {/* Render change plan tool results */}
                      {message.role === 'assistant' && message.toolCalls && message.toolCalls.length > 0 && (
                        <div className="space-y-2 mt-2">
                          {message.toolCalls.filter(tc => isChangePlanTool(tc.name)).map((toolCall, idx) => {
                            // Extract associated plan from other tool calls for context
                            const associatedPlan = message.toolCalls?.find(
                              tc => (tc.name === 'create_change_plan' || tc.name === 'get_change_plan') &&
                                    (tc.result as any)?.plan
                            )?.result as any;

                            return (
                              <ChangePlanToolResult
                                key={toolCall.id || idx}
                                toolName={toolCall.name}
                                result={toolCall.result as any}
                                onValidate={(planId, level) => {
                                  handleSubmit(
                                    { preventDefault: () => {} } as React.FormEvent,
                                    `Validate change plan ${planId} at ${level} level`
                                  );
                                }}
                                onApply={(planId) => handleApplyPlan(planId)}
                                isApplying={!!applyingPlanId}
                                onShare={(planId, targetType) => {
                                  // Extract plan from tool result
                                  const result = toolCall.result as any;
                                  const plan = result?.plan || result;
                                  if (plan && plan.id) {
                                    setShareModal({ plan, targetType });
                                  }
                                }}
                                onSaveToArtifacts={(content) => {
                                  setSaveArtifactModal({ content, messageId: message.id });
                                }}
                                associatedPlan={associatedPlan?.plan}
                              />
                            );
                          })}
                        </div>
                      )}
                    </div>
                    {message.role === 'user' && (
                      <Avatar className="w-6 h-6 flex-shrink-0 mt-0.5">
                        <AvatarFallback className="bg-gradient-to-br from-violet-500 to-purple-600 text-white text-[10px]">
                          {session?.user?.name?.[0] || 'U'}
                        </AvatarFallback>
                      </Avatar>
                    )}
                  </div>
                ))}

                {/* Streaming message display */}
                {streamingMessage && (
                  <div className="flex gap-2">
                    <Avatar className="w-6 h-6 flex-shrink-0 mt-0.5">
                      <AvatarImage src="/pallisade_scout.svg" alt="AI" />
                      <AvatarFallback className="text-[10px]">AI</AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1">
                      <div className="px-1 py-1">
                        {streamingMessage.content ? (
                          <div>
                            <MessageContent content={streamingMessage.content} />
                            {streamingMessage.isStreaming && (
                              <span className="inline-block w-1.5 h-4 bg-violet-400 animate-pulse ml-0.5 align-text-bottom" />
                            )}
                          </div>
                        ) : streamingMessage.isStreaming ? (
                          <div className="flex items-center gap-2">
                            <span className="text-violet-400 text-sm font-mono">
                              {BRAILLE_FRAMES[brailleFrame % BRAILLE_FRAMES.length]}
                            </span>
                            <span className="text-[12px] text-[var(--muted)]">
                              {THINKING_STEPS[thinkingStep % THINKING_STEPS.length]}
                            </span>
                          </div>
                        ) : null}
                      </div>

                      {/* Tool calls in progress */}
                      {streamingMessage.toolCalls.length > 0 && (
                        <div className="mt-2 space-y-1.5">
                          {streamingMessage.toolCalls.map((tc) => {
                            // For completed change plan tools, show the full card
                            if (isChangePlanTool(tc.name) && tc.result && !tc.isExecuting) {
                              const flatResult = {
                                success: tc.result.success,
                                error: tc.result.error,
                                ...(tc.result.data || {}),
                              };
                              return (
                                <ChangePlanToolResult
                                  key={tc.id}
                                  toolName={tc.name}
                                  result={flatResult as any}
                                  onValidate={(planId, level) => {
                                    handleSubmit(
                                      { preventDefault: () => {} } as React.FormEvent,
                                      `Validate change plan ${planId} at ${level} level`
                                    );
                                  }}
                                  onApply={(planId) => handleApplyPlan(planId)}
                                  isApplying={!!applyingPlanId}
                                />
                              );
                            }
                            return (
                              <div
                                key={tc.id}
                                className="flex items-center gap-2 px-3 py-1.5 bg-white/[0.02] border border-white/[0.05] rounded-lg text-[11px]"
                              >
                                {tc.isExecuting ? (
                                  <div className="w-3 h-3 border border-violet-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                                ) : tc.result?.success ? (
                                  <svg className="w-3 h-3 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                  </svg>
                                ) : tc.result?.error ? (
                                  <svg className="w-3 h-3 text-red-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                  </svg>
                                ) : null}
                                <span className="text-white/60 truncate">
                                  {tc.name}
                                  {tc.isExecuting && <span className="text-white/30 ml-1">running...</span>}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {/* Tool confirmation UI */}
                      {streamingMessage.pendingConfirmation && (
                        <ToolConfirmation
                          confirmation={streamingMessage.pendingConfirmation}
                          onConfirm={handleConfirmTool}
                          onDeny={handleDenyTool}
                          isLoading={confirmationLoading}
                        />
                      )}
                    </div>
                  </div>
                )}

                {/* Fallback: show old spinner if loading but no streaming message yet */}
                {isLoading && !streamingMessage && (
                  <div className="flex gap-2">
                    <Avatar className="w-6 h-6 flex-shrink-0">
                      <AvatarImage src="/pallisade_scout.svg" alt="AI" />
                      <AvatarFallback className="text-[10px]">AI</AvatarFallback>
                    </Avatar>
                    <div className="px-1 py-1">
                      <div className="flex items-center gap-2">
                        <span className="text-violet-400 text-sm font-mono">
                          {BRAILLE_FRAMES[brailleFrame % BRAILLE_FRAMES.length]}
                        </span>
                        <span className="text-[12px] text-[var(--muted)]">
                          {THINKING_STEPS[thinkingStep % THINKING_STEPS.length]}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            )}
          </ScrollArea>

          {/* Input - Cursor style */}
          <div className="px-4 pb-4 pt-2">
            <div className="max-w-2xl mx-auto">
              <form onSubmit={handleSubmit}>
                <div className="relative bg-[#1a1a24] border border-white/[0.1] rounded-xl focus-within:border-white/[0.2] transition-colors">
                  {/* @mention autocomplete dropdown */}
                  {showMentionDropdown && (
                    <MentionDropdown
                      items={getFilteredMentionItems()}
                      selectedIndex={selectedMentionIndex}
                      onSelect={handleMentionSelect}
                      onClose={() => setShowMentionDropdown(false)}
                    />
                  )}
                  {/* Textarea */}
                  <Textarea
                    ref={textareaRef}
                    value={input}
                    onChange={handleInputChange}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask about your data pipeline... (type @ to reference integrations)"
                    className="w-full min-h-[80px] max-h-[200px] bg-transparent border-0 focus:ring-0 resize-none px-4 pt-3 pb-14 text-sm placeholder:text-white/30 rounded-xl"
                    rows={2}
                  />

                  {/* Bottom bar with mode selector, model selector, and send button */}
                  <div className="absolute bottom-0 left-0 right-0 flex items-center justify-between px-3 py-2 bg-[#1a1a24] border-t border-white/[0.06] rounded-b-xl">
                    <div className="flex items-center gap-2">
                      <ModeSelector selected={selectedMode} onSelect={setSelectedMode} />
                      <select
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                        className="px-2 py-1 text-[11px] rounded-lg bg-white/[0.04] border border-white/[0.08] text-white/70 focus:outline-none focus:border-white/[0.15] cursor-pointer"
                      >
                        <option value="gpt-5.2">GPT-5.2</option>
                        <option value="gpt-5.2-mini">GPT-5.2 Mini</option>
                        <option value="claude-sonnet">Claude Sonnet</option>
                        <option value="claude-haiku">Claude Haiku</option>
                      </select>
                      <span className="text-[10px] text-white/30 hidden sm:inline">Enter to send</span>
                    </div>
                    {isLoading ? (
                      <Button
                        type="button"
                        onClick={handleStop}
                        size="sm"
                        className="h-7 w-7 p-0"
                        variant="ghost"
                      >
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      </Button>
                    ) : (
                      <Button
                        type="submit"
                        disabled={!input.trim()}
                        size="sm"
                        className="h-7 w-7 p-0"
                      >
                        {Icons.send}
                      </Button>
                    )}
                  </div>
                </div>
              </form>
            </div>
          </div>
        </div>

        {/* Sources Panel */}
        <div className={cn(
          'flex-shrink-0 transition-all duration-300 overflow-hidden',
          showSources ? 'w-80' : 'w-0'
        )}>
          <div className="h-full flex flex-col border-l border-white/[0.06] pl-4 pr-2">
            <div className="py-3 mb-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">Sources</h3>
                <div className="flex items-center gap-1">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={syncSources}
                        disabled={loadingSources}
                        className="p-1.5 h-auto"
                      >
                        <span className={cn(loadingSources && 'animate-spin')}>
                          {Icons.refresh}
                        </span>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Sync sources</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setShowSources(false)}
                        className="p-1.5 h-auto"
                      >
                        {Icons.close}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Close</TooltipContent>
                  </Tooltip>
                </div>
              </div>
              {sourceData.lastSync && (
                <p className="text-[10px] text-[var(--muted)] mt-1">
                  Last synced {new Date(sourceData.lastSync).toLocaleString(undefined, {
                    month: 'short',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit'
                  })}
                </p>
              )}
            </div>

            <ScrollArea className="flex-1 pb-4">
              {loadingSources ? (
                <div className="flex items-center justify-center py-8">
                  <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                </div>
              ) : sourceData.nodes.length === 0 ? (
                <div className="text-center py-8">
                  <div className="w-12 h-12 rounded-xl bg-white/[0.03] border border-white/[0.06] flex items-center justify-center mx-auto mb-3">
                    {Icons.cube}
                  </div>
                  <p className="text-xs text-[var(--muted)]">No connected sources</p>
                  <p className="text-[10px] text-[var(--muted)] mt-1 opacity-60">Connect integrations in Pipeline Builder</p>
                </div>
              ) : (
                <div className="space-y-4 pr-2">
                  {/* Connected Stack */}
                  <div>
                    <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)] mb-2">Connected Stack</h4>
                    <div className="space-y-1.5">
                      {sourceData.nodes.map((node) => (
                        <div key={node.id} className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                          <SourceIcon toolType={node.toolType} />
                          <div className="flex-1 min-w-0">
                            <div className="text-xs font-medium truncate">{node.name}</div>
                            <div className="text-[10px] text-[var(--muted)] capitalize">{node.layer.toLowerCase()}</div>
                          </div>
                          <span className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0" title="Connected" />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* dbt Models */}
                  {sourceData.models.length > 0 && (
                    <SourceSection
                      title="dbt Models"
                      count={sourceData.models.length}
                      items={sourceData.models}
                      renderItem={(model) => (
                        <div key={model.name} className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg hover:bg-white/[0.03] transition-colors">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className={cn(
                              'w-1.5 h-1.5 rounded-full flex-shrink-0',
                              model.materialization === 'incremental' ? 'bg-blue-400' :
                              model.materialization === 'table' ? 'bg-emerald-400' :
                              model.materialization === 'view' ? 'bg-amber-400' : 'bg-[var(--muted)]'
                            )} />
                            <span className="text-xs truncate">{model.name}</span>
                          </div>
                          <span className="text-[10px] text-[var(--muted)] flex-shrink-0">{model.materialization}</span>
                        </div>
                      )}
                      groupBy={(model) => model.schema}
                    />
                  )}

                  {/* Warehouse Tables */}
                  {sourceData.tables.length > 0 && (
                    <SourceSection
                      title="Tables"
                      count={sourceData.tables.length}
                      items={sourceData.tables}
                      renderItem={(table) => (
                        <div key={`${table.schema}.${table.name}`} className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-white/[0.03] transition-colors">
                          <span className="text-[var(--muted)]">{Icons.table}</span>
                          <span className="text-xs truncate">{table.name}</span>
                        </div>
                      )}
                      groupBy={(table) => table.dataset || table.schema}
                    />
                  )}

                  {/* Connectors */}
                  {sourceData.connectors.length > 0 && (
                    <div>
                      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)] mb-2">Connectors</h4>
                      <div className="space-y-1">
                        {sourceData.connectors.map((c) => (
                          <div key={c.name} className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-white/[0.03] transition-colors">
                            <span className="text-xs">{c.name}</span>
                            <span className={cn(
                              'text-[10px]',
                              c.status === 'active' ? 'text-emerald-400' :
                              c.status === 'failed' ? 'text-red-400' : 'text-[var(--muted)]'
                            )}>{c.status}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </ScrollArea>
          </div>
        </div>
      </div>

      {/* Share Plan Modal */}
      {shareModal && (
        <SharePlanModal
          plan={shareModal.plan}
          targetType={shareModal.targetType}
          isOpen={true}
          onClose={() => setShareModal(null)}
          onSuccess={(result) => {
            setShareToast(result);
            setTimeout(() => setShareToast(null), 5000);
          }}
        />
      )}

      {/* Save Artifact Modal */}
      <SaveArtifactModal
        isOpen={!!saveArtifactModal}
        onClose={() => setSaveArtifactModal(null)}
        content={saveArtifactModal?.content || ''}
        sessionId={sessionId}
        messageId={saveArtifactModal?.messageId || ''}
      />

      {/* Share Toast */}
      {shareToast && (
        <div
          className="fixed top-4 right-4 z-50 px-4 py-3 rounded-lg flex items-center gap-3 shadow-lg"
          style={{
            backgroundColor: 'rgba(16, 185, 129, 0.95)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
          }}
        >
          <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          <div>
            <p className="text-sm font-medium text-white">{shareToast.message}</p>
            {shareToast.url && (
              <a
                href={shareToast.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-white/80 hover:underline"
              >
                View
              </a>
            )}
          </div>
          <button
            onClick={() => setShareToast(null)}
            className="p-1 hover:bg-white/10 rounded transition-colors"
          >
            <svg className="w-4 h-4 text-white/80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}
    </TooltipProvider>
  );
}

function SourceIcon({ toolType }: { toolType: string }) {
  const icons: Record<string, string> = {
    bigquery: 'BQ', snowflake: 'SF', postgres: 'PG', redshift: 'RS',
    dbt_cloud: 'dbt', dbt_core: 'dbt',
    fivetran: 'FT', airbyte: 'AB', stitch: 'ST',
    looker: 'LK', tableau: 'TB', metabase: 'MB',
    airflow: 'AF', dagster: 'DG', prefect: 'PF',
  };
  const colors: Record<string, string> = {
    bigquery: 'from-blue-500 to-blue-600',
    snowflake: 'from-cyan-400 to-cyan-500',
    postgres: 'from-indigo-500 to-indigo-600',
    dbt_cloud: 'from-orange-500 to-orange-600',
    dbt_core: 'from-orange-500 to-orange-600',
    fivetran: 'from-pink-500 to-pink-600',
    airbyte: 'from-violet-500 to-violet-600',
  };
  return (
    <div className={cn(
      'w-7 h-7 rounded-lg bg-gradient-to-br flex items-center justify-center flex-shrink-0',
      colors[toolType] || 'from-gray-500 to-gray-600'
    )}>
      <span className="text-[9px] font-bold text-white">{icons[toolType] || toolType.slice(0, 2).toUpperCase()}</span>
    </div>
  );
}

function SourceSection<T>({
  title,
  count,
  items,
  renderItem,
  groupBy,
}: {
  title: string;
  count: number;
  items: T[];
  renderItem: (item: T) => React.ReactNode;
  groupBy: (item: T) => string;
}) {
  const [expanded, setExpanded] = useState(true);

  const groups: Record<string, T[]> = {};
  items.forEach((item) => {
    const key = groupBy(item);
    if (!groups[key]) groups[key] = [];
    groups[key].push(item);
  });

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full mb-2 group"
      >
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">
          {title}
          <span className="ml-1.5 text-[var(--muted)] opacity-60">{count}</span>
        </h4>
        <svg className={cn('w-3.5 h-3.5 text-[var(--muted)] transition-transform', expanded && 'rotate-180')} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded && (
        <div className="space-y-3">
          {Object.entries(groups).map(([groupName, groupItems]) => (
            <div key={groupName}>
              <div className="text-[10px] text-[var(--muted)] font-medium px-3 mb-1 opacity-70">{groupName}</div>
              <div className="space-y-0.5">
                {groupItems.map(renderItem)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MessageContent({ content }: { content: string }) {
  const displayContent = content.replace(/\[FINDING CONTEXT\][\s\S]*?\[QUESTION\]\n?/g, '');
  const segments = parseContentSegments(displayContent);

  return (
    <div className="text-[13px] space-y-2 break-words">
      {segments.map((segment, i) => {
        if (segment.type === 'code') {
          return (
            <CodeBlock
              key={i}
              code={segment.content}
              language={segment.language || 'text'}
            />
          );
        }
        if (segment.type === 'table') {
          return <TableBlock key={i} content={segment.content} />;
        }
        return <TextBlock key={i} content={segment.content} />;
      })}
    </div>
  );
}

type ContentSegment = {
  type: 'text' | 'code' | 'table';
  content: string;
  language?: string;
};

function parseContentSegments(content: string): ContentSegment[] {
  const segments: ContentSegment[] = [];
  const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;

  while ((match = codeBlockRegex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      const textContent = content.slice(lastIndex, match.index).trim();
      if (textContent) {
        parseTextWithTables(textContent, segments);
      }
    }

    segments.push({
      type: 'code',
      language: match[1] || 'text',
      content: match[2].trim(),
    });

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    const textContent = content.slice(lastIndex).trim();
    if (textContent) {
      parseTextWithTables(textContent, segments);
    }
  }

  return segments;
}

// Parse text content and extract tables
function parseTextWithTables(text: string, segments: ContentSegment[]) {
  const lines = text.split('\n');
  let currentText: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Check if this line starts a table (has pipes and next line is separator)
    if (line.includes('|') && i + 1 < lines.length && /^[\s|:-]+$/.test(lines[i + 1])) {
      // Flush current text
      if (currentText.length > 0) {
        segments.push({ type: 'text', content: currentText.join('\n') });
        currentText = [];
      }

      // Extract table
      const tableLines: string[] = [];
      while (i < lines.length && (lines[i].includes('|') || (tableLines.length === 1 && /^[\s|:-]+$/.test(lines[i])))) {
        tableLines.push(lines[i]);
        i++;
      }

      if (tableLines.length >= 2) {
        segments.push({ type: 'table', content: tableLines.join('\n') });
      }
    } else {
      currentText.push(line);
      i++;
    }
  }

  // Flush remaining text
  if (currentText.length > 0) {
    const remaining = currentText.join('\n').trim();
    if (remaining) {
      segments.push({ type: 'text', content: remaining });
    }
  }
}

// Parse and render markdown table
function TableBlock({ content }: { content: string }) {
  const lines = content.trim().split('\n').filter(l => l.trim());
  if (lines.length < 2) return <TextBlock content={content} />;

  // Parse header
  const headerCells = lines[0].split('|').map(c => c.trim()).filter(c => c);

  // Skip separator line (line 1)
  // Parse data rows
  const dataRows = lines.slice(2).map(line =>
    line.split('|').map(c => c.trim()).filter(c => c)
  );

  return (
    <div className="overflow-x-auto rounded-lg border border-white/[0.08]">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="bg-white/[0.04] border-b border-white/[0.08]">
            {headerCells.map((cell, i) => (
              <th key={i} className="px-3 py-2 text-left font-semibold text-white/80">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dataRows.map((row, rowIdx) => (
            <tr key={rowIdx} className="border-b border-white/[0.04] last:border-0 hover:bg-white/[0.02]">
              {row.map((cell, cellIdx) => (
                <td key={cellIdx} className="px-3 py-2 text-white/70">
                  <span dangerouslySetInnerHTML={{ __html: formatInline(cell) }} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const languageLabels: Record<string, string> = {
    sql: 'SQL',
    python: 'Python',
    javascript: 'JavaScript',
    typescript: 'TypeScript',
    bash: 'Bash',
    shell: 'Shell',
    yaml: 'YAML',
    json: 'JSON',
    text: 'Text',
  };

  return (
    <div className="rounded-lg overflow-hidden bg-[#0d0d12] border border-white/[0.08]">
      <div className="flex items-center justify-between px-3 py-1.5 bg-white/[0.02] border-b border-white/[0.06]">
        <span className="text-[10px] font-medium text-[var(--muted)]">
          {languageLabels[language.toLowerCase()] || language.toUpperCase()}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={copyToClipboard}
          className="h-6 px-1.5 gap-1 text-[10px]"
        >
          {copied ? (
            <>
              <svg className="w-3 h-3 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span className="text-emerald-400">Copied</span>
            </>
          ) : (
            <>
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              <span>Copy</span>
            </>
          )}
        </Button>
      </div>
      <pre className="p-3 overflow-x-auto">
        <code className="text-[12px] font-mono text-emerald-300 leading-snug">
          {code}
        </code>
      </pre>
    </div>
  );
}

function TextBlock({ content }: { content: string }) {
  const lines = content.split('\n');

  return (
    <div className="space-y-1 leading-normal">
      {lines.map((line, i) => {
        if (line.startsWith('### ')) {
          const headerText = line.replace(/^###\s*/, '');
          return <h4 key={i} className="font-semibold text-[13px] mt-2 first:mt-0" dangerouslySetInnerHTML={{ __html: formatInline(headerText) }} />;
        }
        if (line.startsWith('## ')) {
          const headerText = line.replace(/^##\s*/, '');
          return <h3 key={i} className="font-semibold text-sm mt-2 first:mt-0" dangerouslySetInnerHTML={{ __html: formatInline(headerText) }} />;
        }
        if (line.startsWith('# ')) {
          const headerText = line.replace(/^#\s*/, '');
          return <h2 key={i} className="font-bold text-[15px] mt-2 first:mt-0" dangerouslySetInnerHTML={{ __html: formatInline(headerText) }} />;
        }
        if (line.startsWith('**') && line.endsWith('**') && !line.slice(2, -2).includes('**')) {
          return <h4 key={i} className="font-semibold text-[13px] mt-2 first:mt-0">{line.replace(/\*\*/g, '')}</h4>;
        }
        if (line.startsWith('- ') || line.startsWith('• ')) {
          return (
            <div key={i} className="flex items-start gap-2 pl-0.5">
              <span className="w-1 h-1 rounded-full bg-current mt-1.5 flex-shrink-0 opacity-40" />
              <span dangerouslySetInnerHTML={{ __html: formatInline(line.replace(/^[-•]\s/, '')) }} />
            </div>
          );
        }
        if (line.match(/^\d+\.\s/)) {
          return (
            <div key={i} className="flex items-start gap-2 pl-0.5">
              <span className="font-medium opacity-60 min-w-[16px] text-right text-[12px]">{line.match(/^(\d+)\./)?.[1]}.</span>
              <span dangerouslySetInnerHTML={{ __html: formatInline(line.replace(/^\d+\.\s/, '')) }} />
            </div>
          );
        }
        if (!line.trim()) return <div key={i} className="h-1.5" />;
        return <p key={i} dangerouslySetInnerHTML={{ __html: formatInline(line) }} />;
      })}
    </div>
  );
}

function formatInline(text: string): string {
  return text
    // Bold - make it white for emphasis
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-white">$1</strong>')
    // Italic - subtle emphasis with opacity
    .replace(/\*([^*]+)\*/g, '<em class="text-white/80 italic">$1</em>')
    // Inline code with smart detection
    .replace(/`([^`]+)`/g, (_match, code) => {
      // File paths (contains / or common extensions)
      if (code.includes('/') || /\.(sql|py|yml|yaml|json|ts|tsx|js|md)$/.test(code)) {
        return `<code class="px-1.5 py-0.5 bg-blue-500/10 border border-blue-500/20 rounded text-[11px] font-mono text-blue-400">${code}</code>`;
      }
      // Table/schema names (uppercase, snake_case with data prefixes, or schema.table pattern)
      if (/^[A-Z][A-Z0-9_]+$/.test(code) || /^\w+\.\w+$/.test(code) || /^(stg_|fct_|dim_|raw_|int_|src_)/.test(code)) {
        return `<code class="px-1.5 py-0.5 bg-purple-500/10 border border-purple-500/20 rounded text-[11px] font-mono text-purple-300">${code}</code>`;
      }
      // Default code styling (data/values) - emerald
      return `<code class="px-1.5 py-0.5 bg-emerald-500/10 border border-emerald-500/20 rounded text-[11px] font-mono text-emerald-300">${code}</code>`;
    })
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-[var(--accent-2)] hover:underline" target="_blank" rel="noopener">$1</a>');
}

export default function AssistantPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-full bg-[#050508]">
        <div className="w-6 h-6 border-2 border-white/20 border-t-white/60 rounded-full animate-spin" />
      </div>
    }>
      <AssistantPageInner />
    </Suspense>
  );
}
