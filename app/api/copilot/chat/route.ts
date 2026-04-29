import { NextResponse } from 'next/server';
import type { Session } from 'next-auth';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { resolveStackIntegrations } from '@/lib/integration-credentials';
import { getBillingState, checkTokenAccess, deductTokens } from '@/lib/billing';
import { scannerClient } from '@/lib/scanner-client';

export async function POST(request: Request) {
  try {
    const session = await auth();
    if (!session?.user?.email) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    // Get user and organization
    const user = await prisma.user.findUnique({
      where: { email: session.user.email },
      select: { id: true, organizationId: true },
    });

    if (!user?.organizationId) {
      return NextResponse.json({ error: 'No organization' }, { status: 400 });
    }

    // Billing enforcement — pre-request check
    const billingState = await getBillingState(user.organizationId);
    const enforcement = checkTokenAccess(billingState);
    if (!enforcement.allowed) {
      return NextResponse.json({ error: enforcement.reason }, { status: 402 });
    }

    const body = await request.json();
    const {
      message,
      sessionId,
      pipeline_stack_id,
      pipelineStackId, // Support both formats
      node_ids,
      referenced_entities,
      model = 'gpt-5.4',
      mode = 'ask',
      stream = false,
      confirmed_tool_ids,
    } = body;

    const effectivePipelineStackId = pipelineStackId || pipeline_stack_id;

    if (!message) {
      return NextResponse.json({ error: 'Message required' }, { status: 400 });
    }

    // If streaming requested, delegate to the streaming handler
    if (stream) {
      return handleStreamingChat(request, body, user as { id: string; organizationId: string }, session as Session);
    }

    // Get or create chat session
    let chatSession;
    if (sessionId) {
      // Verify session belongs to user
      chatSession = await prisma.copilotSession.findFirst({
        where: {
          id: sessionId,
          userId: user.id,
        },
      });
      if (!chatSession) {
        return NextResponse.json({ error: 'Session not found' }, { status: 404 });
      }
    } else {
      // Create new session with pipeline context
      chatSession = await prisma.copilotSession.create({
        data: {
          title: 'New Chat',
          userId: user.id,
          organizationId: user.organizationId,
          model,
          pipelineStackId: effectivePipelineStackId || null,
        },
      });
    }

    // Fetch conversation history for context
    const previousMessages = await prisma.copilotMessage.findMany({
      where: { sessionId: chatSession.id },
      orderBy: { createdAt: 'asc' },
      select: {
        role: true,
        content: true,
      },
    });

    // Save user message to database
    const userMessage = await prisma.copilotMessage.create({
      data: {
        sessionId: chatSession.id,
        role: 'USER',
        content: message,
      },
    });

    // Build conversation history for the AI
    const conversationHistory = [
      ...previousMessages.map(m => ({
        role: m.role.toLowerCase() as 'user' | 'assistant',
        content: m.content,
      })),
      { role: 'user' as const, content: message },
    ];

    // Resolve all integration credentials (from Integration table, with legacy PipelineNode fallback)
    const integrations = await resolveStackIntegrations(effectivePipelineStackId, user.organizationId);

    // Fetch lineage data from database to pass to copilot
    let lineageData: { nodes: any[]; edges: any[] } = { nodes: [], edges: [] };
    if (effectivePipelineStackId) {
      try {
        const [lineageNodes, lineageEdges] = await Promise.all([
          prisma.lineageNode.findMany({
            where: {
              organizationId: user.organizationId,
              pipelineStackId: effectivePipelineStackId,
            },
            select: {
              id: true,
              name: true,
              database: true,
              schema: true,
              tableName: true,
              nodeType: true,
              description: true,
              upstreamCount: true,
              downstreamCount: true,
            },
          }),
          prisma.lineageEdge.findMany({
            where: {
              organizationId: user.organizationId,
              pipelineStackId: effectivePipelineStackId,
            },
            select: {
              id: true,
              sourceId: true,
              targetId: true,
              edgeType: true,
              columns: true,
            },
          }),
        ]);

        lineageData = {
          nodes: lineageNodes.map(n => ({
            id: n.id,
            name: n.name,
            fqn: n.name, // name is already FQN format
            database: n.database,
            schema: n.schema,
            node_type: n.nodeType,
            description: n.description,
            upstream_count: n.upstreamCount,
            downstream_count: n.downstreamCount,
          })),
          edges: lineageEdges.map(e => ({
            id: e.id,
            source_id: e.sourceId,
            target_id: e.targetId,
            edge_type: e.edgeType,
            columns: e.columns,
          })),
        };

        console.log(`[COPILOT] Fetched lineage: ${lineageData.nodes.length} nodes, ${lineageData.edges.length} edges`);
      } catch (e) {
        console.error('[COPILOT] Failed to fetch lineage:', e);
      }
    }

    // Call the scanner copilot API with full conversation history
    const response = await scannerClient.fetch(session, '/api/v1/copilot/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message,
        messages: conversationHistory, // Full conversation history for context
        session_id: chatSession.id,
        pipeline_stack_id: effectivePipelineStackId || pipeline_stack_id,
        node_ids,
        referenced_entities,
        model,
        mode, // Interaction mode (ask, debug, plan, create, etc.)
        integrations, // Pass integrations from pipeline nodes
        lineage: lineageData, // Pass pre-fetched lineage data
      }),
    });

    let aiContent: string;
    let toolCalls: any[] = [];
    let inputTokens = 0;
    let outputTokens = 0;
    let responseMode = mode;

    if (!response.ok) {
      // If scanner API is not available, return a helpful message
      const errorText = await response.text();
      console.error('Scanner API error:', errorText);
      aiContent = getLocalFallbackResponse(message);
    } else {
      const data = await response.json();
      aiContent = data.message || getLocalFallbackResponse(message);
      toolCalls = data.tool_calls || [];
      inputTokens = data.input_tokens || 0;
      outputTokens = data.output_tokens || 0;
      responseMode = data.mode || mode;
    }

    // Save AI response to database
    const aiMessage = await prisma.copilotMessage.create({
      data: {
        sessionId: chatSession.id,
        role: 'ASSISTANT',
        content: aiContent,
        toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
        inputTokens,
        outputTokens,
      },
    });

    // Update session title if this is the first message (generate from user message)
    const messageCount = await prisma.copilotMessage.count({
      where: { sessionId: chatSession.id },
    });
    
    if (messageCount <= 2) {
      // Generate title from first user message
      const title = generateSessionTitle(message);
      await prisma.copilotSession.update({
        where: { id: chatSession.id },
        data: {
          title,
          totalInputTokens: { increment: inputTokens },
          totalOutputTokens: { increment: outputTokens },
        },
      });
    } else {
      // Just update token counts
      await prisma.copilotSession.update({
        where: { id: chatSession.id },
        data: {
          totalInputTokens: { increment: inputTokens },
          totalOutputTokens: { increment: outputTokens },
        },
      });
    }

    // Billing: deduct tokens from org ledger
    await deductTokens(user.organizationId, inputTokens, outputTokens);

    return NextResponse.json({
      sessionId: chatSession.id,
      message: aiContent,
      messageId: aiMessage.id,
      mode: responseMode,
      tool_calls: toolCalls,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
    });

  } catch (error) {
    console.error('Copilot chat error:', error);
    
    // Return a local fallback response
    const body = await request.clone().json().catch(() => ({}));
    return NextResponse.json({
      sessionId: body.sessionId || null,
      message: getLocalFallbackResponse(body.message || ''),
      tool_calls: [],
      input_tokens: 0,
      output_tokens: 0,
    });
  }
}

/**
 * Generate a short, descriptive session title from the first user message
 */
function generateSessionTitle(message: string): string {
  // Remove context blocks and clean up
  let cleanMessage = message
    .replace(/\[FINDING CONTEXT\][\s\S]*?\[QUESTION\]\n?/g, '')
    .replace(/```[\s\S]*?```/g, '[code]') // Replace code blocks
    .replace(/`[^`]+`/g, '') // Remove inline code
    .replace(/\n+/g, ' ') // Replace newlines with spaces
    .trim();

  // If very short, return as-is
  if (cleanMessage.length <= 40) {
    return cleanMessage;
  }

  // Extract key phrases based on common patterns
  const patterns = [
    /(?:how (?:do i|can i|to)|what(?:'s| is| are)|show me|find|get|query|check|analyze|debug|fix|explain|list|count|compare)\s+(.{10,60}?)(?:\?|$|\.|\n)/i,
    /(?:why (?:is|are|does|do)|when (?:did|does|was)|where (?:is|are))\s+(.{10,60}?)(?:\?|$|\.|\n)/i,
  ];

  for (const pattern of patterns) {
    const match = cleanMessage.match(pattern);
    if (match) {
      let title = match[0].replace(/[?.!]+$/, '').trim();
      // Capitalize first letter
      title = title.charAt(0).toUpperCase() + title.slice(1);
      if (title.length <= 50) {
        return title;
      }
    }
  }

  // Fallback: smart truncation
  // Remove filler words at the start
  const fillerStart = /^(hey|hi|hello|please|can you|could you|i want to|i need to|i'd like to|help me)\s+/i;
  cleanMessage = cleanMessage.replace(fillerStart, '');

  // Capitalize first letter
  cleanMessage = cleanMessage.charAt(0).toUpperCase() + cleanMessage.slice(1);

  // Truncate at word boundary
  if (cleanMessage.length <= 45) {
    return cleanMessage;
  }

  const truncated = cleanMessage.substring(0, 42);
  const lastSpace = truncated.lastIndexOf(' ');
  if (lastSpace > 25) {
    return truncated.substring(0, lastSpace) + '...';
  }
  return truncated + '...';
}

function getLocalFallbackResponse(message: string): string {
  const lowerMessage = message.toLowerCase();

  if (lowerMessage.includes('upstream') || lowerMessage.includes('downstream')) {
    return `I can help you explore lineage. To trace dependencies:

1. Go to the **Lineage** page in the sidebar
2. Search for your table or model
3. Click on a node to see its connections

Once you connect your data warehouse or dbt, I'll be able to automatically trace lineage for you.`;
  }

  if (lowerMessage.includes('stale') || lowerMessage.includes('fresh')) {
    return `To check data freshness:

1. Ensure your data warehouse is connected in **Integrations**
2. I'll query your tables' last update times
3. Compare against your SLOs

Connect Snowflake, BigQuery, or PostgreSQL to enable automatic freshness checking.`;
  }

  if (lowerMessage.includes('fail') || lowerMessage.includes('error')) {
    return `To debug pipeline failures:

1. Connect your orchestrator (Airflow, Dagster, or Prefect)
2. I can then check recent runs and get logs
3. We can trace the failure through your pipeline

What orchestrator are you using?`;
  }

  return `I'm your data pipeline assistant. I can help you:

- **Explore lineage** - See what feeds into and depends on your data
- **Check freshness** - Find stale tables and SLO breaches
- **Debug issues** - Trace failures through your pipeline
- **Understand impact** - See blast radius of changes

Connect your data tools in **Integrations** to unlock full AI assistance.`;
}

// ============================================
// STREAMING HANDLER
// ============================================

async function handleStreamingChat(
  _request: Request,
  body: any,
  user: { id: string; organizationId: string },
  session: Session,
) {
  const {
    message: rawMessage,
    sessionId,
    pipeline_stack_id,
    pipelineStackId,
    node_ids,
    referenced_entities,
    model = 'gpt-5.4',
    mode = 'ask',
    confirmed_tool_ids,
    pending_tool_call,
  } = body;

  // Parse __action:* messages
  let confirmedArtifacts: Record<string, any> | undefined;
  let displayMessage = rawMessage;
  let message = rawMessage;

  if (rawMessage.startsWith('__action:confirm:')) {
    // Format: __action:confirm:<artifactId>:<toolName>[:<editedDataJSON>]
    const withoutPrefix = rawMessage.slice('__action:confirm:'.length);
    const firstColon = withoutPrefix.indexOf(':');
    const artifactId = firstColon === -1 ? withoutPrefix : withoutPrefix.slice(0, firstColon);
    const rest = firstColon === -1 ? '' : withoutPrefix.slice(firstColon + 1);

    const secondColon = rest.indexOf(':');
    const toolName = secondColon === -1 ? rest : rest.slice(0, secondColon);
    const jsonPart = secondColon === -1 ? '' : rest.slice(secondColon + 1);

    let editedData: Record<string, any> | undefined;
    if (jsonPart) {
      try {
        editedData = JSON.parse(jsonPart);
      } catch (e) {
        // No valid JSON, treat as confirm without edits
      }
    }

    confirmedArtifacts = {
      [artifactId]: {
        tool_name: toolName,
        ...(editedData || {}),
      },
    };
    displayMessage = `Confirmed: ${toolName.replace(/_/g, ' ')} (${artifactId})`;
    message = displayMessage;
  } else if (rawMessage.startsWith('__action:cancel:')) {
    const artifactId = rawMessage.split(':')[2];
    displayMessage = `Cancelled action ${artifactId}`;
    message = displayMessage;
  }

  const effectivePipelineStackId = pipelineStackId || pipeline_stack_id;

  // Billing enforcement — pre-request check
  const billingState = await getBillingState(user.organizationId);
  const enforcement = checkTokenAccess(billingState);
  if (!enforcement.allowed) {
    return NextResponse.json({ error: enforcement.reason }, { status: 402 });
  }

  // Get or create chat session
  let chatSession;
  if (sessionId) {
    chatSession = await prisma.copilotSession.findFirst({
      where: { id: sessionId, userId: user.id },
    });
    if (!chatSession) {
      return NextResponse.json({ error: 'Session not found' }, { status: 404 });
    }
  } else {
    chatSession = await prisma.copilotSession.create({
      data: {
        title: 'New Chat',
        userId: user.id,
        organizationId: user.organizationId,
        model,
        pipelineStackId: effectivePipelineStackId || null,
      },
    });
  }

  // Fetch conversation history
  const previousMessages = await prisma.copilotMessage.findMany({
    where: { sessionId: chatSession.id },
    orderBy: { createdAt: 'asc' },
    select: { role: true, content: true },
  });

  // Save user message (skip for confirmation/cancel actions and tool resumes)
  const isActionMessage = rawMessage.startsWith('__action:');
  if (!isActionMessage && (!confirmed_tool_ids || confirmed_tool_ids.length === 0)) {
    await prisma.copilotMessage.create({
      data: {
        sessionId: chatSession.id,
        role: 'USER',
        content: displayMessage,
      },
    });
  }

  const conversationHistory = [
    ...previousMessages.map((m: { role: string; content: string }) => ({
      role: m.role.toLowerCase() as 'user' | 'assistant',
      content: m.content,
    })),
    { role: 'user' as const, content: displayMessage },
  ];

  // Resolve all integration credentials (from Integration table, with legacy PipelineNode fallback)
  const integrations = await resolveStackIntegrations(effectivePipelineStackId, user.organizationId);

  // Fetch lineage data
  let lineageData: { nodes: any[]; edges: any[] } = { nodes: [], edges: [] };
  if (effectivePipelineStackId) {
    try {
      const [lineageNodes, lineageEdges] = await Promise.all([
        prisma.lineageNode.findMany({
          where: {
            organizationId: user.organizationId,
            pipelineStackId: effectivePipelineStackId,
          },
          select: {
            id: true, name: true, database: true, schema: true, tableName: true,
            nodeType: true, description: true, upstreamCount: true, downstreamCount: true,
          },
        }),
        prisma.lineageEdge.findMany({
          where: {
            organizationId: user.organizationId,
            pipelineStackId: effectivePipelineStackId,
          },
          select: { id: true, sourceId: true, targetId: true, edgeType: true, columns: true },
        }),
      ]);
      lineageData = {
        nodes: lineageNodes.map(n => ({
          id: n.id, name: n.name, fqn: n.name, database: n.database, schema: n.schema,
          node_type: n.nodeType, description: n.description,
          upstream_count: n.upstreamCount, downstream_count: n.downstreamCount,
        })),
        edges: lineageEdges.map(e => ({
          id: e.id, source_id: e.sourceId, target_id: e.targetId,
          edge_type: e.edgeType, columns: e.columns,
        })),
      };
    } catch (e) {
      console.error('[COPILOT/Stream] Failed to fetch lineage:', e);
    }
  }

  // Call FastAPI streaming endpoint
  const scannerResponse = await scannerClient.fetch(session, '/api/v1/copilot/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      messages: conversationHistory,
      session_id: chatSession.id,
      pipeline_stack_id: effectivePipelineStackId || pipeline_stack_id,
      node_ids,
      referenced_entities,
      model,
      mode,
      integrations,
      lineage: lineageData,
      confirmed_tool_ids: confirmed_tool_ids || [],
      pending_tool_call: pending_tool_call || null,
      confirmed_artifacts: confirmedArtifacts,
    }),
  });

  if (!scannerResponse.ok || !scannerResponse.body) {
    const errorText = await scannerResponse.text();
    console.error('[COPILOT/Stream] Scanner API error:', errorText);
    return NextResponse.json({ error: errorText }, { status: 500 });
  }

  // Accumulate content from SSE events for DB persistence
  let accumulatedContent = '';
  let allToolCalls: any[] = [];
  let inputTokens = 0;
  let outputTokens = 0;
  let stopReason = '';
  const sessionIdForSave = chatSession.id;

  const encoder = new TextEncoder();
  const decoder = new TextDecoder();

  // Prepend session_info event, proxy SSE stream, then save to DB on completion
  const stream = new ReadableStream({
    async start(controller) {
      // Inject session_info as first event
      const sessionEvent = `event: session_info\ndata: ${JSON.stringify({ sessionId: chatSession.id })}\n\n`;
      controller.enqueue(encoder.encode(sessionEvent));

      const reader = scannerResponse.body!.getReader();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          // Forward raw bytes to client
          controller.enqueue(value);

          // Also parse events for DB accumulation
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split('\n\n');
          buffer = events.pop()!; // keep incomplete event

          for (const eventStr of events) {
            if (!eventStr.trim()) continue;
            const lines = eventStr.split('\n');
            const eventLine = lines.find(l => l.startsWith('event: '));
            const dataLine = lines.find(l => l.startsWith('data: '));
            if (!eventLine || !dataLine) continue;

            const eventType = eventLine.slice(7);
            try {
              const data = JSON.parse(dataLine.slice(6));
              if (eventType === 'text_delta') {
                accumulatedContent += data.content || '';
              } else if (eventType === 'tool_call_result') {
                allToolCalls.push({
                  tool: data.tool_name,
                  input: data.arguments,
                  result: data.result,
                });
              } else if (eventType === 'done') {
                inputTokens = data.input_tokens || 0;
                outputTokens = data.output_tokens || 0;
                stopReason = data.stop_reason || '';
                // Use tool_calls from done event if available (more complete)
                if (data.tool_calls && data.tool_calls.length > 0) {
                  allToolCalls = data.tool_calls;
                }
              }
            } catch { /* skip unparseable events */ }
          }
        }
      } catch (err) {
        console.error('[COPILOT/Stream] Error reading scanner stream:', err);
        const errorEvent = `event: error\ndata: ${JSON.stringify({ message: 'Stream interrupted' })}\n\n`;
        controller.enqueue(encoder.encode(errorEvent));
      }

      // Stream complete — save to DB
      try {
        if (accumulatedContent) {
          await prisma.copilotMessage.create({
            data: {
              sessionId: sessionIdForSave,
              role: 'ASSISTANT',
              content: accumulatedContent,
              toolCalls: allToolCalls.length > 0 ? allToolCalls : undefined,
              inputTokens,
              outputTokens,
            },
          });

          // Update session title if first message
          const messageCount = await prisma.copilotMessage.count({
            where: { sessionId: sessionIdForSave },
          });
          if (messageCount <= 2) {
            await prisma.copilotSession.update({
              where: { id: sessionIdForSave },
              data: {
                title: generateSessionTitle(message),
                totalInputTokens: { increment: inputTokens },
                totalOutputTokens: { increment: outputTokens },
              },
            });
          } else {
            await prisma.copilotSession.update({
              where: { id: sessionIdForSave },
              data: {
                totalInputTokens: { increment: inputTokens },
                totalOutputTokens: { increment: outputTokens },
              },
            });
          }

          // Billing: deduct tokens from org ledger
          await deductTokens(user.organizationId, inputTokens, outputTokens);
        }
      } catch (saveErr) {
        console.error('[COPILOT/Stream] Failed to save to DB:', saveErr);
      }

      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    },
  });
}
