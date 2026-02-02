'use client';

import { useState, useRef, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: ToolCall[];
  timestamp: Date;
}

interface ToolCall {
  name: string;
  input: Record<string, unknown>;
  output?: string;
  status: 'pending' | 'completed' | 'error';
}

interface ChatSession {
  id: string;
  title: string;
  date: string;
  preview: string;
}

// Mock chat sessions
const mockSessions: ChatSession[] = [
  { id: '1', title: 'Debug stale data in dim_customers', date: '2 hours ago', preview: 'The dim_customers table appears to be...' },
  { id: '2', title: 'What tables depend on raw.orders?', date: 'Yesterday', preview: 'Let me trace the lineage for raw.orders...' },
  { id: '3', title: 'Fix failing dbt test', date: '2 days ago', preview: 'I found the issue with your dbt test...' },
];

// Suggested prompts
const suggestedPrompts = [
  { icon: '🔍', text: 'What tables have stale data?', category: 'debug' },
  { icon: '📊', text: 'Show me the lineage for dim_customers', category: 'lineage' },
  { icon: '🔧', text: 'Why is my dbt model failing?', category: 'debug' },
  { icon: '📈', text: 'Which dashboards use fct_orders?', category: 'lineage' },
];

export default function ChatPage() {
  const searchParams = useSearchParams();
  const sessionId = searchParams.get('session');
  
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedModel, setSelectedModel] = useState('claude-sonnet');
  const [showSessionList, setShowSessionList] = useState(false);
  const [currentSession, setCurrentSession] = useState<string | null>(sessionId);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 200) + 'px';
    }
  }, [input]);

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    // Simulate API call
    try {
      const response = await fetch('/api/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMessage.content,
          sessionId: currentSession,
          model: selectedModel,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        const assistantMessage: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: data.content || data.message || 'I apologize, but I encountered an issue processing your request.',
          toolCalls: data.toolCalls,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, assistantMessage]);
      } else {
        // Fallback response
        const assistantMessage: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: 'I\'m currently unable to connect to the AI service. Please make sure the scanner backend is running and try again.',
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, assistantMessage]);
      }
    } catch (error) {
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: 'I encountered an error while processing your request. Please try again.',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const startNewChat = () => {
    setMessages([]);
    setCurrentSession(null);
    setShowSessionList(false);
  };

  const selectPrompt = (prompt: string) => {
    setInput(prompt);
    inputRef.current?.focus();
  };

  return (
    <div className="flex h-[calc(100vh-56px)] -m-6">
      {/* Session Sidebar */}
      <div className={`
        ${showSessionList ? 'w-72' : 'w-0'} 
        flex-shrink-0 border-r border-white/[0.04] bg-[#030303]
        transition-all duration-200 overflow-hidden
      `}>
        <div className="w-72 h-full flex flex-col">
          {/* New Chat Button */}
          <div className="p-3 border-b border-white/[0.06]">
            <button
              onClick={startNewChat}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-white text-[13px] font-medium transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              New Chat
            </button>
          </div>

          {/* Session List */}
          <div className="flex-1 overflow-y-auto p-2">
            <div className="text-[11px] font-medium text-white/40 uppercase tracking-wide px-2 py-2">
              Recent
            </div>
            {mockSessions.map((session) => (
              <button
                key={session.id}
                onClick={() => setCurrentSession(session.id)}
                className={`
                  w-full text-left p-3 rounded-lg mb-1 transition-colors
                  ${currentSession === session.id 
                    ? 'bg-white/[0.08] text-white' 
                    : 'hover:bg-white/[0.04] text-white/70'
                  }
                `}
              >
                <p className="text-[13px] font-medium truncate mb-0.5">{session.title}</p>
                <p className="text-[11px] text-white/40">{session.date}</p>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Chat Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowSessionList(!showSessionList)}
              className="p-2 rounded-lg hover:bg-white/[0.05] text-white/50 hover:text-white transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            </button>
            <h2 className="text-[14px] font-medium text-white">
              {currentSession ? 'Chat' : 'New Chat'}
            </h2>
          </div>

          {/* Model Selector */}
          <div className="flex items-center gap-2">
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="px-3 py-1.5 rounded-lg bg-white/[0.05] border border-white/[0.08] text-[13px] text-white/80 focus:outline-none focus:border-white/[0.15]"
            >
              <option value="claude-sonnet">Claude Sonnet</option>
              <option value="claude-opus">Claude Opus</option>
            </select>
          </div>
        </div>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            /* Empty State */
            <div className="h-full flex flex-col items-center justify-center px-4">
              <div className="max-w-xl w-full text-center">
                <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center mx-auto mb-6 shadow-lg shadow-[var(--accent)]/20">
                  <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                  </svg>
                </div>
                <h2 className="text-xl font-semibold text-white mb-2">How can I help?</h2>
                <p className="text-white/50 text-[14px] mb-8">
                  Ask questions about your data stack, debug issues, or explore lineage
                </p>

                {/* Suggested Prompts */}
                <div className="grid grid-cols-2 gap-2">
                  {suggestedPrompts.map((prompt, i) => (
                    <button
                      key={i}
                      onClick={() => selectPrompt(prompt.text)}
                      className="flex items-center gap-3 p-3 rounded-lg bg-white/[0.03] border border-white/[0.06] hover:border-white/[0.12] text-left transition-colors"
                    >
                      <span className="text-lg">{prompt.icon}</span>
                      <span className="text-[13px] text-white/70">{prompt.text}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            /* Messages */
            <div className="max-w-3xl mx-auto py-6 px-4">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`mb-6 ${message.role === 'user' ? 'flex justify-end' : ''}`}
                >
                  {message.role === 'user' ? (
                    <div className="max-w-[85%] px-4 py-3 rounded-2xl bg-[var(--accent)]/20 text-white">
                      <p className="text-[14px] whitespace-pre-wrap">{message.content}</p>
                    </div>
                  ) : (
                    <div className="flex gap-3">
                      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center flex-shrink-0 mt-0.5">
                        <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                        </svg>
                      </div>
                      <div className="flex-1 min-w-0">
                        {/* Tool Calls */}
                        {message.toolCalls && message.toolCalls.length > 0 && (
                          <div className="mb-3 space-y-2">
                            {message.toolCalls.map((tool, i) => (
                              <div
                                key={i}
                                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.06] text-[12px]"
                              >
                                <div className={`w-1.5 h-1.5 rounded-full ${
                                  tool.status === 'completed' ? 'bg-emerald-500' :
                                  tool.status === 'error' ? 'bg-red-500' : 'bg-amber-500'
                                }`} />
                                <span className="text-white/50">Called</span>
                                <code className="text-white/80 font-mono">{tool.name}</code>
                              </div>
                            ))}
                          </div>
                        )}
                        <div className="text-[14px] text-white/90 leading-relaxed whitespace-pre-wrap">
                          {message.content}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
              
              {/* Loading indicator */}
              {isLoading && (
                <div className="flex gap-3 mb-6">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center flex-shrink-0">
                    <svg className="w-4 h-4 text-white animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                    </svg>
                  </div>
                  <div className="flex items-center gap-1 px-3 py-2">
                    <div className="w-2 h-2 rounded-full bg-white/30 animate-bounce" style={{ animationDelay: '0ms' }} />
                    <div className="w-2 h-2 rounded-full bg-white/30 animate-bounce" style={{ animationDelay: '150ms' }} />
                    <div className="w-2 h-2 rounded-full bg-white/30 animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="border-t border-white/[0.06] p-4">
          <div className="max-w-3xl mx-auto">
            <form onSubmit={handleSubmit} className="relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about your data stack..."
                rows={1}
                className="w-full px-4 py-3 pr-12 rounded-xl bg-white/[0.05] border border-white/[0.08] text-white placeholder-white/40 resize-none focus:outline-none focus:border-white/[0.15] text-[14px]"
              />
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="absolute right-2 bottom-2 p-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] disabled:opacity-50 disabled:hover:bg-[var(--accent)] transition-colors"
              >
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
                </svg>
              </button>
            </form>
            <p className="text-center text-[11px] text-white/30 mt-2">
              Press Enter to send, Shift+Enter for new line
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
