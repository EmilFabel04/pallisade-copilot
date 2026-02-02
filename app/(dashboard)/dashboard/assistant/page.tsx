'use client';

import { useState, useRef, useEffect } from 'react';
import { useSession } from 'next-auth/react';

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
};

type Finding = {
  id: string;
  title: string;
  severity: string;
  description?: string;
  table?: string;
  category?: string;
  ai_context?: any;
  has_auto_fix?: boolean;
  auto_fix?: { code?: string };
};

type Report = {
  id: string;
  title: string;
  type: string;
  findings: Finding[];
};

export default function AssistantPage() {
  const { data: session } = useSession();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loadingFindings, setLoadingFindings] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Fetch recent findings
  useEffect(() => {
    fetchFindings();
  }, []);

  const fetchFindings = async () => {
    try {
      const response = await fetch('/api/reports?limit=10');
      if (response.ok) {
        const data = await response.json();
        const allFindings: Finding[] = [];
        (data.reports || []).forEach((report: Report) => {
          if (report.findings && Array.isArray(report.findings)) {
            report.findings.slice(0, 3).forEach((f: Finding, idx: number) => {
              allFindings.push({
                ...f,
                id: f.id || `${report.id}-${idx}`,
              });
            });
          }
        });
        setFindings(allFindings.slice(0, 6)); // Top 6 findings
      }
    } catch (error) {
      console.error('Failed to fetch findings:', error);
    } finally {
      setLoadingFindings(false);
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
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageText,
          sessionId,
        }),
      });

      if (!response.ok) throw new Error('Failed to get response');

      const data = await response.json();
      if (data.sessionId) setSessionId(data.sessionId);

      const aiMessage: Message = {
        id: data.message?.id || (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.message?.content || getLocalResponse(messageText),
        timestamp: new Date(),
      };

      setMessages(prev => [...prev, aiMessage]);
    } catch {
      const aiMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: getLocalResponse(messageText),
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, aiMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const askAboutFinding = (finding: Finding, question: string) => {
    const context = `
[FINDING CONTEXT]
Title: ${finding.title}
Severity: ${finding.severity}
${finding.table ? `Table: ${finding.table}` : ''}
${finding.description ? `Description: ${finding.description}` : ''}
${finding.ai_context?.hours_stale ? `Hours Stale: ${finding.ai_context.hours_stale}` : ''}
${finding.ai_context?.slo_hours ? `SLO: ${finding.ai_context.slo_hours} hours` : ''}
${finding.has_auto_fix ? `Has Auto-Fix: Yes` : ''}

[QUESTION]
${question}`;

    handleSubmit({ preventDefault: () => {} } as React.FormEvent, context);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setSessionId(null);
  };

  const severityColor = (severity: string) => {
    switch (severity) {
      case 'critical': return 'text-red-400 bg-red-500/10';
      case 'high': return 'text-amber-400 bg-amber-500/10';
      case 'medium': return 'text-slate-300 bg-slate-500/10';
      default: return 'text-blue-400 bg-blue-500/10';
    }
  };

  return (
    <div className="h-[calc(100vh-120px)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-[rgba(255,255,255,0.06)] mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center">
            <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-semibold">AI Assistant</h1>
            <p className="text-xs text-[var(--muted)]">Ask about your scan findings</p>
          </div>
        </div>
        {messages.length > 0 && (
          <button 
            onClick={clearChat}
            className="px-3 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--text)] hover:bg-[rgba(255,255,255,0.05)] rounded-lg transition-all"
          >
            Clear Chat
          </button>
        )}
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-hidden flex gap-6">
        {/* Chat Area */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 overflow-y-auto space-y-4 pr-2">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center px-4">
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center mb-4">
                  <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                  </svg>
                </div>
                <h2 className="text-lg font-semibold mb-2">Ask me anything</h2>
                <p className="text-sm text-[var(--muted)] max-w-sm mb-6">
                  I can help explain your findings, suggest fixes, and prioritize what to work on first.
                </p>
                
                {/* Quick prompts */}
                <div className="flex flex-wrap gap-2 justify-center max-w-lg">
                  {[
                    "What should I fix first?",
                    "Summarize my scan results",
                    "How do I add dbt freshness tests?",
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
          <div className="mt-4 pt-4 border-t border-[rgba(255,255,255,0.06)]">
            <form onSubmit={handleSubmit}>
              <div className="flex gap-2">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about your findings..."
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

        {/* Findings Sidebar */}
        <div className="w-80 flex-shrink-0 hidden lg:block">
          <div className="dashboard-card p-4 h-full overflow-hidden flex flex-col">
            <h3 className="font-medium text-sm mb-3">Your Findings</h3>
            
            {loadingFindings ? (
              <div className="flex-1 flex items-center justify-center">
                <div className="w-6 h-6 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
              </div>
            ) : findings.length === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center text-center">
                <p className="text-sm text-[var(--muted)] mb-2">No findings yet</p>
                <a href="/dashboard/reports/new" className="text-xs text-[var(--accent-2)] hover:underline">
                  Run a scan →
                </a>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto space-y-3">
                {findings.map((finding) => (
                  <div key={finding.id} className="p-3 bg-[rgba(255,255,255,0.02)] rounded-lg border border-[rgba(255,255,255,0.05)]">
                    <div className="flex items-start gap-2 mb-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium uppercase ${severityColor(finding.severity)}`}>
                        {finding.severity}
                      </span>
                    </div>
                    <p className="text-xs font-medium mb-2 line-clamp-2">{finding.title}</p>
                    {finding.table && (
                      <p className="text-[10px] text-[var(--muted)] font-mono mb-2">{finding.table}</p>
                    )}
                    
                    {/* Quick Questions */}
                    <div className="flex flex-wrap gap-1">
                      <button
                        onClick={() => askAboutFinding(finding, "Why does this matter? What's the business impact?")}
                        className="px-2 py-1 text-[10px] bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] rounded text-[var(--muted)] hover:text-[var(--text)] transition-all"
                      >
                        Why does this matter?
                      </button>
                      <button
                        onClick={() => askAboutFinding(finding, "How critical is this? Should I fix it immediately?")}
                        className="px-2 py-1 text-[10px] bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] rounded text-[var(--muted)] hover:text-[var(--text)] transition-all"
                      >
                        How critical?
                      </button>
                      <button
                        onClick={() => askAboutFinding(finding, "How do I fix this? Give me step-by-step instructions.")}
                        className="px-2 py-1 text-[10px] bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] rounded text-[var(--muted)] hover:text-[var(--text)] transition-all"
                      >
                        How to fix?
                      </button>
                      {finding.has_auto_fix && (
                        <button
                          onClick={() => askAboutFinding(finding, "Explain the auto-fix code. What does it do and how do I apply it?")}
                          className="px-2 py-1 text-[10px] bg-emerald-500/10 hover:bg-emerald-500/20 rounded text-emerald-400 transition-all"
                        >
                          Explain auto-fix
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageContent({ content }: { content: string }) {
  // Remove context blocks from display
  const displayContent = content.replace(/\[FINDING CONTEXT\][\s\S]*?\[QUESTION\]\n?/g, '');
  const lines = displayContent.split('\n');
  
  return (
    <div className="text-sm space-y-1.5">
      {lines.map((line, i) => {
        // Headers with ### or ##
        if (line.startsWith('### ')) {
          return <h4 key={i} className="font-semibold mt-3 first:mt-0">{line.replace(/^###\s*/, '')}</h4>;
        }
        if (line.startsWith('## ')) {
          return <h3 key={i} className="font-semibold text-base mt-3 first:mt-0">{line.replace(/^##\s*/, '')}</h3>;
        }
        if (line.startsWith('# ')) {
          return <h2 key={i} className="font-bold text-lg mt-3 first:mt-0">{line.replace(/^#\s*/, '')}</h2>;
        }
        // Bold text as headers
        if (line.startsWith('**') && line.endsWith('**')) {
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
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-[rgba(0,0,0,0.3)] rounded text-[11px] font-mono">$1</code>');
}

function getLocalResponse(query: string): string {
  const lowerQuery = query.toLowerCase();
  
  // Check if it's a finding-specific question
  if (query.includes('[FINDING CONTEXT]')) {
    const titleMatch = query.match(/Title: (.+)/);
    const severityMatch = query.match(/Severity: (\w+)/);
    const tableMatch = query.match(/Table: (.+)/);
    const hoursStaleMatch = query.match(/Hours Stale: ([\d.]+)/);
    const sloMatch = query.match(/SLO: (\d+)/);
    
    const title = titleMatch?.[1] || 'this issue';
    const severity = severityMatch?.[1] || 'medium';
    const table = tableMatch?.[1];
    const hoursStale = hoursStaleMatch?.[1];
    const slo = sloMatch?.[1];

    if (lowerQuery.includes('why does this matter')) {
      return `**Why ${title} Matters**

${severity === 'critical' ? '🔴 **Critical Impact** - This requires immediate attention.' : severity === 'high' ? '🟠 **High Impact** - This should be addressed soon.' : '🟡 **Moderate Impact** - Plan to fix this in your next sprint.'}

**Business Impact:**
${table ? `- The \`${table}\` table is a core data asset` : ''}
${hoursStale && slo ? `- Data is ${hoursStale} hours stale vs your ${slo}h SLO` : ''}
- Downstream reports and dashboards show outdated information
- Business decisions may be made on stale data
- Stakeholder trust in data quality erodes over time

**Technical Impact:**
- Any models depending on this data are also affected
- Alert fatigue if this becomes a recurring issue
- Potential cascade failures in your data pipeline

Would you like me to help you create a fix for this?`;
    }

    if (lowerQuery.includes('how critical') || lowerQuery.includes('immediately')) {
      const urgency = severity === 'critical' ? 'Yes, fix this immediately!' : severity === 'high' ? 'High priority - fix within 24 hours' : 'Medium priority - schedule for this sprint';
      return `**Priority Assessment: ${title}**

**Urgency:** ${urgency}

**Severity Breakdown:**
- Current severity: **${severity.toUpperCase()}**
${hoursStale && slo ? `- SLO breach: ${Math.round(parseFloat(hoursStale) - parseInt(slo))} hours overdue` : ''}

**Recommendation:**
${severity === 'critical' ? `1. Stop what you're doing and investigate
2. Check your pipeline orchestrator for failures
3. Apply the auto-fix if available
4. Set up alerting to catch this earlier` : 
severity === 'high' ? `1. Add this to your current sprint
2. Investigate root cause
3. Implement the fix within 24-48 hours
4. Monitor for recurrence` :
`1. Add to your backlog
2. Group with similar issues
3. Fix in your next maintenance window`}

Need help with the specific fix steps?`;
    }

    if (lowerQuery.includes('how do i fix') || lowerQuery.includes('step-by-step')) {
      return `**How to Fix: ${title}**

${table ? `**Affected Table:** \`${table}\`\n` : ''}

**Step-by-Step Fix:**

1. **Investigate the cause**
   - Check your pipeline orchestrator for failed jobs
   - Look at recent deployments that may have affected the pipeline
   - Verify source system availability

2. **Apply the immediate fix**
   ${query.includes('Has Auto-Fix: Yes') ? '- Use the auto-fix code from the Fix Queue\n   - Test in staging first' : '- Manually trigger a pipeline refresh\n   - Or fix the underlying pipeline issue'}

3. **Add monitoring**
   - Add a freshness test to your dbt project
   - Set up Slack/PagerDuty alerts for SLO breaches

4. **Prevent recurrence**
   - Add retry logic to your pipeline
   - Consider adding data quality checks upstream

Would you like the specific code for any of these steps?`;
    }

    if (lowerQuery.includes('auto-fix') || lowerQuery.includes('explain')) {
      return `**Understanding the Auto-Fix**

The auto-fix code adds a **freshness test** to your dbt project. Here's what it does:

**What the code does:**
- Monitors the \`${table || 'table'}\` for data freshness
- Warns when data is ${slo || '24'} hours old
- Errors when data is ${slo ? parseInt(slo) * 2 : 48} hours old

**How to apply it:**
1. Copy the YAML from the Fix Queue
2. Add it to your \`sources.yml\` file
3. Run \`dbt test\` to verify it works
4. Commit and push to your repo

**What happens next:**
- dbt will check freshness on every run
- You'll get early warnings before SLO breaches
- Failed freshness tests block downstream models

Want me to customize the thresholds for your use case?`;
    }
  }

  // Generic responses
  if (lowerQuery.includes('fix first') || lowerQuery.includes('priorit')) {
    return `**What to Fix First**

Based on severity and impact, here's my recommendation:

**🔴 Critical (Fix Now)**
- Any tables that are significantly overdue on their SLO
- Exposed secrets or credentials

**🟠 High (Fix This Week)**  
- Tables approaching SLO breach
- Pipeline failures affecting multiple downstream models

**🟡 Medium (Fix This Sprint)**
- Minor freshness issues
- Non-critical pipeline warnings

My tip: Start with items that have **auto-fixes available** - they're quickest to resolve and give you momentum.

Check your Fix Queue for the full prioritized list!`;
  }

  if (lowerQuery.includes('summarize') || lowerQuery.includes('results')) {
    return `I'll summarize your scan results. Check your dashboard for the latest numbers, but typically I look at:

**Key Metrics:**
- Overall DRR Score
- Critical vs High vs Medium issues
- Number of auto-fixes available

**Common Patterns:**
- Freshness issues often indicate pipeline problems
- Multiple tables affected = systemic issue
- Single table = likely isolated incident

Go to your **Reports** page for detailed breakdowns, or ask me about specific findings!`;
  }

  if (lowerQuery.includes('dbt') && lowerQuery.includes('freshness')) {
    return `**Adding dbt Freshness Tests**

Here's how to add freshness monitoring to your dbt project:

**1. Add to sources.yml:**
\`\`\`yaml
sources:
  - name: your_source
    tables:
      - name: your_table
        loaded_at_field: updated_at
        freshness:
          warn_after: {count: 24, period: hour}
          error_after: {count: 48, period: hour}
\`\`\`

**2. Run the test:**
\`dbt source freshness\`

**3. Add to CI/CD:**
Include \`dbt source freshness\` in your pipeline to catch issues early.

Want me to customize this for a specific table?`;
  }

  return `I can help you with that! Here are some things I can do:

- **Explain findings** - Tell me about a specific issue
- **Prioritize work** - Help you decide what to fix first  
- **Guide fixes** - Step-by-step instructions
- **Customize auto-fixes** - Adapt the generated code

Try clicking on a finding in the sidebar and asking a specific question!`;
}
