'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';
import { usePipeline } from '@/contexts/PipelineContext';

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
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
};

const AVAILABLE_MODELS = [
  { id: 'gpt-4o', name: 'GPT-4o', provider: 'OpenAI', description: 'Most capable' },
  { id: 'gpt-4o-mini', name: 'GPT-4o Mini', provider: 'OpenAI', description: 'Fast & efficient' },
  { id: 'o3-mini', name: 'o3-mini', provider: 'OpenAI', description: 'Reasoning model' },
  { id: 'claude-sonnet', name: 'Claude Sonnet', provider: 'Anthropic', description: 'Balanced' },
  { id: 'claude-opus', name: 'Claude Opus', provider: 'Anthropic', description: 'Most capable' },
];

export default function AssistantPage() {
  const { data: session } = useSession();
  const { selectedPipelineId, selectedPipeline } = usePipeline();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [showHistory, setShowHistory] = useState(true);
  const [selectedModel, setSelectedModel] = useState('gpt-4o');
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [sourceData, setSourceData] = useState<SourceData>({ nodes: [], tables: [], models: [], connectors: [] });
  const [loadingSources, setLoadingSources] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lastPipelineId = useRef<string | null>(null);
  const modelLoadedRef = useRef(false);

  // Load model from localStorage on client
  useEffect(() => {
    if (!modelLoadedRef.current) {
      const saved = localStorage.getItem('pallisade-copilot-model');
      if (saved) setSelectedModel(saved);
      modelLoadedRef.current = true;
    }
  }, []);

  // Persist model selection to localStorage
  useEffect(() => {
    if (modelLoadedRef.current) {
      localStorage.setItem('pallisade-copilot-model', selectedModel);
    }
  }, [selectedModel]);

  // Fetch sources when pipeline changes
  useEffect(() => {
    if (selectedPipelineId) fetchSources(selectedPipelineId);
  }, [selectedPipelineId]);

  const fetchSources = async (pipelineId: string) => {
    setLoadingSources(true);
    try {
      const res = await fetch(`/api/pipeline?id=${pipelineId}`);
      if (!res.ok) return;
      const data = await res.json();
      const stack = data.stack;
      if (!stack?.nodes) return;

      const connectedNodes = stack.nodes.filter((n: any) => n.status === 'CONNECTED' || n.status === 'ACTIVE');
      const allTables: SourceData['tables'] = [];
      const allModels: SourceData['models'] = [];
      const allConnectors: SourceData['connectors'] = [];

      await Promise.all(connectedNodes.map(async (node: any) => {
        try {
          const nodeRes = await fetch(`/api/pipeline/${pipelineId}/nodes/${node.id}/tables`);
          if (!nodeRes.ok) return;
          const nodeData = await nodeRes.json();
          if (nodeData.tables) allTables.push(...nodeData.tables);
          if (nodeData.models) allModels.push(...nodeData.models);
          if (nodeData.connectors) allConnectors.push(...nodeData.connectors);
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
      });
    } catch (error) {
      console.error('Failed to fetch sources:', error);
    } finally {
      setLoadingSources(false);
    }
  };

  // Fetch sessions when pipeline changes
  useEffect(() => {
    // Skip if pipeline hasn't changed
    if (lastPipelineId.current === selectedPipelineId) return;
    lastPipelineId.current = selectedPipelineId;

    fetchSessions();
  }, [selectedPipelineId]);

  const fetchSessions = async () => {
    try {
      setLoadingSessions(true);
      const url = selectedPipelineId 
        ? `/api/copilot/sessions?limit=30&pipelineStackId=${selectedPipelineId}`
        : '/api/copilot/sessions?limit=30';
      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        setSessions(data.sessions || []);
        
        // Auto-load most recent session if exists for this pipeline
        if (data.sessions && data.sessions.length > 0) {
          loadSession(data.sessions[0].id);
        } else {
          // No sessions for this pipeline - start fresh
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

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  }, [input]);

  const handleSubmit = async (e: React.FormEvent, customMessage?: string) => {
    e.preventDefault();
    const messageText = customMessage || input.trim();
    if (!messageText || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageText,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    if (!customMessage) setInput('');
    setIsLoading(true);

    try {
      const response = await fetch('/api/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageText,
          sessionId,
          pipelineStackId: selectedPipelineId,
          model: selectedModel,
        }),
      });

      if (!response.ok) throw new Error('Failed to get response');

      const data = await response.json();
      
      // Update session ID if new session was created
      if (data.sessionId && data.sessionId !== sessionId) {
        setSessionId(data.sessionId);
        // Refresh sessions list to show new session
        const url = selectedPipelineId 
          ? `/api/copilot/sessions?limit=30&pipelineStackId=${selectedPipelineId}`
          : '/api/copilot/sessions?limit=30';
        const sessionsRes = await fetch(url);
        if (sessionsRes.ok) {
          const sessionsData = await sessionsRes.json();
          setSessions(sessionsData.sessions || []);
        }
      }

      const aiMessage: Message = {
        id: data.messageId || (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.message || 'Sorry, I encountered an error.',
        timestamp: new Date(),
      };

      setMessages(prev => [...prev, aiMessage]);
    } catch (error) {
      console.error('Chat error:', error);
      const aiMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, aiMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
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
    <div className="h-[calc(100vh-120px)] flex">
      {/* Chat History Sidebar */}
      <div className={`${showHistory ? 'w-72' : 'w-0'} flex-shrink-0 transition-all duration-200 overflow-hidden`}>
        <div className="h-full flex flex-col border-r border-[rgba(255,255,255,0.06)] pr-4">
          {/* New Chat Button */}
          <button
            onClick={startNewChat}
            className="flex items-center gap-2 px-4 py-3 mb-4 bg-[var(--accent)] hover:bg-[var(--accent)]/80 text-white rounded-xl transition-all"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            <span className="font-medium">New Chat</span>
          </button>

          {/* Sessions List */}
          <div className="flex-1 overflow-y-auto space-y-1">
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
                <button
                  key={s.id}
                  onClick={() => loadSession(s.id)}
                  className={`w-full text-left px-3 py-2.5 rounded-lg transition-all group ${
                    sessionId === s.id
                      ? 'bg-[rgba(255,255,255,0.08)] text-white'
                      : 'hover:bg-[rgba(255,255,255,0.04)] text-[var(--muted)] hover:text-white'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{s.title}</div>
                      <div className="text-xs opacity-50 mt-0.5">{formatDate(s.updatedAt)}</div>
                    </div>
                    <button
                      onClick={(e) => deleteSession(s.id, e)}
                      className="p-1 opacity-0 group-hover:opacity-50 hover:!opacity-100 transition-opacity"
                      title="Delete chat"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-[rgba(255,255,255,0.06)] mb-4 pl-4">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="p-2 hover:bg-[rgba(255,255,255,0.05)] rounded-lg transition-all"
              title={showHistory ? 'Hide history' : 'Show history'}
            >
              <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center">
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
            </div>
            <div>
              <h1 className="text-xl font-semibold">AI Assistant</h1>
              <p className="text-xs text-[var(--muted)]">Ask about your data pipeline</p>
            </div>
          </div>
          
          {/* Sources + Model Selector */}
          <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSources(!showSources)}
            className={`flex items-center gap-2 px-3 py-2 text-sm border rounded-lg transition-all ${
              showSources
                ? 'bg-[rgba(255,255,255,0.08)] border-[rgba(255,255,255,0.15)] text-white'
                : 'bg-[rgba(255,255,255,0.03)] hover:bg-[rgba(255,255,255,0.06)] border-[rgba(255,255,255,0.08)] text-[var(--muted)]'
            }`}
            title={showSources ? 'Hide sources' : 'Show sources'}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
            </svg>
            <span>Sources</span>
            {sourceData.nodes.length > 0 && (
              <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-emerald-500/20 text-emerald-400">
                {sourceData.nodes.length}
              </span>
            )}
          </button>
          <div className="relative">
            <button
              onClick={() => setShowModelPicker(!showModelPicker)}
              className="flex items-center gap-2 px-3 py-2 text-sm bg-[rgba(255,255,255,0.03)] hover:bg-[rgba(255,255,255,0.06)] border border-[rgba(255,255,255,0.08)] rounded-lg transition-all"
            >
              <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 15.5m14.8-.2l-4.3.008m-5.5.492V18a1 1 0 001 1h4a1 1 0 001-1v-2.7" />
              </svg>
              <span className="text-[var(--text)]">{AVAILABLE_MODELS.find(m => m.id === selectedModel)?.name || selectedModel}</span>
              <svg className={`w-4 h-4 text-[var(--muted)] transition-transform ${showModelPicker ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            
            {showModelPicker && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowModelPicker(false)} />
                <div className="absolute right-0 top-full mt-2 w-64 bg-[#1a1a24] border border-[rgba(255,255,255,0.1)] rounded-xl shadow-xl z-20 overflow-hidden">
                  <div className="p-3 border-b border-[rgba(255,255,255,0.06)]">
                    <h4 className="text-sm font-medium">Select Model</h4>
                    <p className="text-xs text-[var(--muted)] mt-0.5">Choose the AI model for this chat</p>
                  </div>
                  <div className="max-h-64 overflow-y-auto">
                    {AVAILABLE_MODELS.map((model) => (
                      <button
                        key={model.id}
                        onClick={() => {
                          setSelectedModel(model.id);
                          setShowModelPicker(false);
                        }}
                        className={`w-full p-3 text-left hover:bg-[rgba(255,255,255,0.04)] transition-colors flex items-center justify-between gap-2 ${
                          selectedModel === model.id ? 'bg-[rgba(255,255,255,0.06)]' : ''
                        }`}
                      >
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{model.name}</span>
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[rgba(255,255,255,0.08)] text-[var(--muted)]">{model.provider}</span>
                          </div>
                          <p className="text-xs text-[var(--muted)] mt-0.5">{model.description}</p>
                        </div>
                        {selectedModel === model.id && (
                          <svg className="w-4 h-4 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-4 pr-2 pl-4">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center px-4">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center mb-4">
                <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold mb-2">How can I help?</h2>
              <p className="text-sm text-[var(--muted)] max-w-sm mb-6">
                I can query your data warehouse, explore lineage, and help debug pipeline issues.
              </p>
              
              {/* Quick prompts */}
              <div className="flex flex-wrap gap-2 justify-center max-w-lg">
                {[
                  "How many rows are in my tables?",
                  "What's the freshness of my analytics data?",
                  "Show me my pipeline dependencies",
                ].map((prompt, i) => (
                  <button
                    key={i}
                    onClick={() => handleSubmit({ preventDefault: () => {} } as React.FormEvent, prompt)}
                    className="px-3 py-2 text-sm bg-[rgba(255,255,255,0.03)] hover:bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.08)] rounded-lg text-[var(--muted)] hover:text-[var(--text)] transition-all"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((message) => (
                <div key={message.id} className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : ''}`}>
                  {message.role === 'assistant' && (
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center flex-shrink-0">
                      <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                      </svg>
                    </div>
                  )}
                  <div className={`max-w-[80%] ${
                    message.role === 'user' 
                      ? 'bg-[var(--accent)] text-white rounded-2xl rounded-tr-md px-4 py-2.5' 
                      : 'bg-[rgba(255,255,255,0.03)] rounded-2xl rounded-tl-md px-4 py-3'
                  }`}>
                    <MessageContent content={message.content} />
                  </div>
                  {message.role === 'user' && (
                    <div className="w-8 h-8 rounded-lg bg-[rgba(255,255,255,0.1)] flex items-center justify-center flex-shrink-0 text-sm font-medium">
                      {session?.user?.name?.[0] || 'U'}
                    </div>
                  )}
                </div>
              ))}
              
              {isLoading && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center flex-shrink-0">
                    <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                    </svg>
                  </div>
                  <div className="bg-[rgba(255,255,255,0.03)] rounded-2xl rounded-tl-md px-4 py-3">
                    <div className="flex gap-1">
                      <div className="w-2 h-2 rounded-full bg-[var(--muted)] animate-bounce" />
                      <div className="w-2 h-2 rounded-full bg-[var(--muted)] animate-bounce" style={{ animationDelay: '0.1s' }} />
                      <div className="w-2 h-2 rounded-full bg-[var(--muted)] animate-bounce" style={{ animationDelay: '0.2s' }} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Input */}
        <div className="mt-4 pt-4 border-t border-[rgba(255,255,255,0.06)] pl-4">
          <form onSubmit={handleSubmit}>
            <div className="flex gap-2">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about your data..."
                className="flex-1 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:border-[var(--accent)]/50"
                rows={1}
              />
              <button 
                type="submit" 
                disabled={!input.trim() || isLoading}
                className="px-4 bg-[var(--accent)] text-white rounded-xl hover:bg-[var(--accent)]/80 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* Sources Panel */}
      <div className={`${showSources ? 'w-80' : 'w-0'} flex-shrink-0 transition-all duration-200 overflow-hidden`}>
        <div className="h-full flex flex-col border-l border-[rgba(255,255,255,0.06)] pl-4 pr-2">
          <div className="flex items-center justify-between py-3 mb-2">
            <h3 className="text-sm font-semibold">Sources</h3>
            <button onClick={() => setShowSources(false)} className="p-1 hover:bg-[rgba(255,255,255,0.05)] rounded transition-all">
              <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-4 pb-4">
            {loadingSources ? (
              <div className="flex items-center justify-center py-8">
                <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
              </div>
            ) : sourceData.nodes.length === 0 ? (
              <div className="text-center py-8">
                <svg className="w-8 h-8 text-[var(--muted)] mx-auto mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                </svg>
                <p className="text-xs text-[var(--muted)]">No connected sources</p>
                <p className="text-[10px] text-[var(--muted)] mt-1 opacity-60">Connect integrations in Pipeline Builder</p>
              </div>
            ) : (
              <>
                {/* Connected Stack */}
                <div>
                  <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)] mb-2">Connected Stack</h4>
                  <div className="space-y-1.5">
                    {sourceData.nodes.map((node) => (
                      <div key={node.id} className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.06)]">
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
                      <div key={model.name} className="flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md hover:bg-[rgba(255,255,255,0.03)] transition-colors">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                            model.materialization === 'incremental' ? 'bg-blue-400' :
                            model.materialization === 'table' ? 'bg-emerald-400' :
                            model.materialization === 'view' ? 'bg-amber-400' : 'bg-[var(--muted)]'
                          }`} />
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
                      <div key={`${table.schema}.${table.name}`} className="flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-[rgba(255,255,255,0.03)] transition-colors">
                        <svg className="w-3 h-3 text-[var(--muted)] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
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
                        <div key={c.name} className="flex items-center justify-between px-2.5 py-1.5 rounded-md hover:bg-[rgba(255,255,255,0.03)] transition-colors">
                          <span className="text-xs">{c.name}</span>
                          <span className={`text-[10px] ${c.status === 'active' ? 'text-emerald-400' : c.status === 'failed' ? 'text-red-400' : 'text-[var(--muted)]'}`}>{c.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
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
    <div className={`w-7 h-7 rounded-md bg-gradient-to-br ${colors[toolType] || 'from-gray-500 to-gray-600'} flex items-center justify-center flex-shrink-0`}>
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

  // Group items
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
        <svg className={`w-3.5 h-3.5 text-[var(--muted)] transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded && (
        <div className="space-y-3">
          {Object.entries(groups).map(([groupName, groupItems]) => (
            <div key={groupName}>
              <div className="text-[10px] text-[var(--muted)] font-medium px-2.5 mb-1 opacity-70">{groupName}</div>
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
  // Remove context blocks from display
  const displayContent = content.replace(/\[FINDING CONTEXT\][\s\S]*?\[QUESTION\]\n?/g, '');
  
  // Parse content into segments (text and code blocks)
  const segments = parseContentSegments(displayContent);
  
  return (
    <div className="text-sm font-mono tracking-tight space-y-3">
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
        return <TextBlock key={i} content={segment.content} />;
      })}
    </div>
  );
}

type ContentSegment = {
  type: 'text' | 'code';
  content: string;
  language?: string;
};

function parseContentSegments(content: string): ContentSegment[] {
  const segments: ContentSegment[] = [];
  const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;

  while ((match = codeBlockRegex.exec(content)) !== null) {
    // Add text before code block
    if (match.index > lastIndex) {
      const textContent = content.slice(lastIndex, match.index).trim();
      if (textContent) {
        segments.push({ type: 'text', content: textContent });
      }
    }
    
    // Add code block
    segments.push({
      type: 'code',
      language: match[1] || 'text',
      content: match[2].trim(),
    });
    
    lastIndex = match.index + match[0].length;
  }
  
  // Add remaining text
  if (lastIndex < content.length) {
    const textContent = content.slice(lastIndex).trim();
    if (textContent) {
      segments.push({ type: 'text', content: textContent });
    }
  }
  
  return segments;
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
    <div className="rounded-lg overflow-hidden bg-[#1e1e2e] border border-[rgba(255,255,255,0.08)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-[rgba(255,255,255,0.03)] border-b border-[rgba(255,255,255,0.06)]">
        <span className="text-xs font-medium text-[var(--muted)]">
          {languageLabels[language.toLowerCase()] || language.toUpperCase()}
        </span>
        <button
          onClick={copyToClipboard}
          className="flex items-center gap-1.5 px-2 py-1 text-xs text-[var(--muted)] hover:text-white hover:bg-[rgba(255,255,255,0.08)] rounded transition-all"
        >
          {copied ? (
            <>
              <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span className="text-emerald-400">Copied!</span>
            </>
          ) : (
            <>
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      {/* Code */}
      <pre className="p-4 overflow-x-auto">
        <code className="text-[13px] font-mono text-emerald-300 leading-relaxed">
          {code}
        </code>
      </pre>
    </div>
  );
}

function TextBlock({ content }: { content: string }) {
  const lines = content.split('\n');
  
  return (
    <div className="space-y-1.5">
      {lines.map((line, i) => {
        // Headers with ### or ##
        if (line.startsWith('### ')) {
          const headerText = line.replace(/^###\s*/, '');
          return <h4 key={i} className="font-semibold mt-3 first:mt-0" dangerouslySetInnerHTML={{ __html: formatInline(headerText) }} />;
        }
        if (line.startsWith('## ')) {
          const headerText = line.replace(/^##\s*/, '');
          return <h3 key={i} className="font-semibold text-base mt-3 first:mt-0" dangerouslySetInnerHTML={{ __html: formatInline(headerText) }} />;
        }
        if (line.startsWith('# ')) {
          const headerText = line.replace(/^#\s*/, '');
          return <h2 key={i} className="font-bold text-lg mt-3 first:mt-0" dangerouslySetInnerHTML={{ __html: formatInline(headerText) }} />;
        }
        // Bold text as headers (standalone bold line)
        if (line.startsWith('**') && line.endsWith('**') && !line.slice(2, -2).includes('**')) {
          return <h4 key={i} className="font-semibold mt-3 first:mt-0">{line.replace(/\*\*/g, '')}</h4>;
        }
        // Bullet lists
        if (line.startsWith('- ') || line.startsWith('• ')) {
          return (
            <div key={i} className="flex items-start gap-2 pl-1">
              <span className="w-1 h-1 rounded-full bg-current mt-2 flex-shrink-0 opacity-50" />
              <span dangerouslySetInnerHTML={{ __html: formatInline(line.replace(/^[-•]\s/, '')) }} />
            </div>
          );
        }
        // Numbered lists
        if (line.match(/^\d+\.\s/)) {
          return (
            <div key={i} className="flex items-start gap-2 pl-1">
              <span className="font-medium opacity-70 min-w-[16px]">{line.match(/^(\d+)\./)?.[1]}.</span>
              <span dangerouslySetInnerHTML={{ __html: formatInline(line.replace(/^\d+\.\s/, '')) }} />
            </div>
          );
        }
        // Empty lines
        if (!line.trim()) return <div key={i} className="h-2" />;
        // Regular text
        return <p key={i} dangerouslySetInnerHTML={{ __html: formatInline(line) }} />;
      })}
    </div>
  );
}

function formatInline(text: string): string {
  return text
    // Bold text
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold">$1</strong>')
    // Italic text
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code class="px-1.5 py-0.5 bg-[rgba(0,0,0,0.3)] rounded text-[11px] font-mono text-emerald-300">$1</code>')
    // Links [text](url)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-[var(--accent-2)] hover:underline" target="_blank">$1</a>');
}
