import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

export async function POST(request: Request) {
  try {
    const session = await getServerSession(authOptions);
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

    const body = await request.json();
    const {
      message,
      sessionId,
      pipeline_stack_id,
      pipelineStackId, // Support both formats
      node_ids,
      referenced_entities,
      model = 'gpt-5.2',
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
      return handleStreamingChat(request, body, user as { id: string; organizationId: string });
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

    // Fetch pipeline nodes (integrations) from the selected pipeline
    // Include all nodes except ERROR status - PENDING nodes with config are valid
    const pipelineStack = await prisma.pipelineStack.findFirst({
      where: {
        organizationId: user.organizationId,
        ...(effectivePipelineStackId ? { id: effectivePipelineStackId } : {}),
      },
      include: {
        nodes: {
          where: {
            status: { notIn: ['ERROR', 'TESTING'] },
          },
          select: {
            id: true,
            name: true,
            toolType: true,
            layer: true,
            status: true,
            config: true,
          },
        },
      },
    });

    console.log(`[COPILOT] Found ${pipelineStack?.nodes.length || 0} pipeline nodes:`,
      pipelineStack?.nodes.map(n => ({ name: n.name, type: n.toolType, status: n.status, hasConfig: !!n.config })));

    // Convert pipeline nodes to integration format for the scanner
    // Note: type must be uppercase to match the scanner's tool registry
    const validActiveStatuses = ['CONNECTED', 'HEALTHY', 'WARNING'];
    const integrations = pipelineStack?.nodes.map(node => {
      // Decrypt credentials if encrypted (same pattern as tables/route.ts)
      let credentials: Record<string, any> = {};
      if (node.config) {
        try {
          const configJson = node.config as { encrypted?: string; _cached?: any; [key: string]: any };

          if (configJson.encrypted) {
            // Decrypt if credentials are encrypted
            const decrypted = decrypt(configJson.encrypted);
            credentials = JSON.parse(decrypted);
            console.log(`[COPILOT] Decrypted config for ${node.name} (${node.toolType}), keys:`, Object.keys(credentials));
          } else {
            // Config is stored directly (not encrypted)
            const { _cached, ...creds } = configJson;
            credentials = creds;
            console.log(`[COPILOT] Direct config for ${node.name} (${node.toolType}), keys:`, Object.keys(credentials));
          }
        } catch (e) {
          console.error(`[COPILOT] Failed to decrypt credentials for ${node.name}:`, e);
          credentials = {};
        }
      } else {
        console.log(`[COPILOT] No config for ${node.name} (${node.toolType})`);
      }

      // Map frontend field names to adapter field names
      const config = { ...credentials };
      const toolType = node.toolType.toUpperCase();

      // username -> user (Snowflake, Postgres, Redshift only — other integrations
      // like Airflow need 'username' kept as-is for their MCP env mappings)
      const usernameToUserTypes = ['SNOWFLAKE', 'POSTGRES', 'REDSHIFT'];
      if (usernameToUserTypes.includes(toolType) && config.username && !config.user) {
        config.user = config.username;
        delete config.username;
      }

      // server -> host (SQL Server variants only)
      const serverToHostTypes = ['SQLSERVER', 'AZURE_SQL', 'AZURE_SYNAPSE'];
      if (serverToHostTypes.includes(toolType) && config.server && !config.host) {
        config.host = config.server;
        delete config.server;
      }

      // host -> base_url (Airflow pipeline nodes use 'host' but MCP/adapters expect 'base_url')
      if (toolType === 'AIRFLOW' && config.host && !config.base_url) {
        config.base_url = config.host;
        delete config.host;
      }

      // n8n: host -> base_url (adapter accepts both, but be consistent)
      if (toolType === 'N8N' && config.host && !config.base_url) {
        config.base_url = config.host;
      }

      return {
        id: node.id,
        name: node.name,
        type: node.toolType.toUpperCase(),
        layer: node.layer.toLowerCase(),
        status: validActiveStatuses.includes(node.status) ? 'ACTIVE' : node.status,
        config,
        metadata: {},
      };
    }) || [];

    // Warn about duplicate integration types (e.g. two Airflow nodes)
    const typeCounts = integrations.reduce((acc, i) => {
      acc[i.type] = (acc[i.type] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
    for (const [type, count] of Object.entries(typeCounts)) {
      if (count > 1) {
        console.warn(`[COPILOT] WARNING: ${count} ${type} nodes found in pipeline. Only the first will be used by MCP. Remove duplicates in Pipeline settings.`);
        const dupes = integrations.filter(i => i.type === type);
        dupes.forEach((d, idx) => {
          console.warn(`[COPILOT]   ${type} #${idx + 1}: name="${d.name}", username="${d.config?.username}", base_url="${d.config?.base_url || d.config?.host}"`);
        });
      }
    }

    // Also fetch OAuth integrations (GitHub, Slack, Jira) from the Integration table
    const oauthIntegrations = await prisma.integration.findMany({
      where: {
        organizationId: user.organizationId,
        status: 'ACTIVE',
      },
      select: {
        id: true,
        name: true,
        type: true,
        status: true,
        accessToken: true,
        metadata: true,
      },
    });

    console.log(`[COPILOT] Found ${oauthIntegrations.length} OAuth integrations:`, oauthIntegrations.map(o => ({ id: o.id, type: o.type, hasToken: !!o.accessToken })));

    // Convert OAuth integrations to the same format and merge
    for (const oauth of oauthIntegrations) {
      // Decrypt access token if present
      let accessToken = '';
      if (oauth.accessToken) {
        try {
          accessToken = decrypt(oauth.accessToken);
        } catch (e) {
          console.error(`[COPILOT] Failed to decrypt token for ${oauth.name}:`, e);
        }
      }

      // Check if this type already exists (from pipeline nodes)
      const existingIdx = integrations.findIndex(i => i.type === oauth.type.toUpperCase());
      if (existingIdx >= 0) {
        // Merge the OAuth token into the existing integration's config
        // This ensures pipeline nodes get the OAuth credentials
        console.log(`[COPILOT] Merging OAuth token for ${oauth.type} into existing pipeline node at index ${existingIdx}`);
        integrations[existingIdx].config = {
          ...integrations[existingIdx].config,
          access_token: accessToken,
          token: accessToken,
        };
        integrations[existingIdx].metadata = {
          ...integrations[existingIdx].metadata,
          ...(oauth.metadata as Record<string, any> || {}),
        };
        continue;
      }
      console.log(`[COPILOT] No existing pipeline node for ${oauth.type}, adding as standalone integration`);

      integrations.push({
        id: oauth.id,
        name: oauth.name,
        type: oauth.type.toUpperCase(),
        layer: 'version_control',
        status: oauth.status === 'ACTIVE' ? 'ACTIVE' : oauth.status,
        config: {
          access_token: accessToken,
          token: accessToken,
        },
        metadata: oauth.metadata as Record<string, any> || {},
      });
    }

    console.log('[COPILOT] Sending integrations to scanner:', integrations.map(i => ({
      name: i.name,
      type: i.type,
      status: i.status,
      configKeys: Object.keys(i.config || {}),
      configKeyCount: Object.keys(i.config || {}).length,
      hasToken: !!(i.config?.access_token || i.config?.token),
    })));

    // Fetch lineage data from database to pass to copilot
    let lineageData: { nodes: any[]; edges: any[] } = { nodes: [], edges: [] };
    try {
      const [lineageNodes, lineageEdges] = await Promise.all([
        prisma.lineageNode.findMany({
          where: { organizationId: user.organizationId },
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
          where: { organizationId: user.organizationId },
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

    // Call the scanner copilot API with full conversation history
    const response = await fetch(`${SCANNER_API_URL}/api/v1/copilot/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Organization-Id': user.organizationId,
      },
      body: JSON.stringify({
        message,
        messages: conversationHistory, // Full conversation history for context
        session_id: chatSession.id,
        pipeline_stack_id: pipeline_stack_id || pipelineStack?.id,
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
) {
  const {
    message,
    sessionId,
    pipeline_stack_id,
    pipelineStackId,
    node_ids,
    referenced_entities,
    model = 'gpt-5.2',
    mode = 'ask',
    confirmed_tool_ids,
    pending_tool_call,
  } = body;

  const effectivePipelineStackId = pipelineStackId || pipeline_stack_id;

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

  // Save user message (only on first call, not on confirmation resumes)
  if (!confirmed_tool_ids || confirmed_tool_ids.length === 0) {
    await prisma.copilotMessage.create({
      data: {
        sessionId: chatSession.id,
        role: 'USER',
        content: message,
      },
    });
  }

  const conversationHistory = [
    ...previousMessages.map((m: { role: string; content: string }) => ({
      role: m.role.toLowerCase() as 'user' | 'assistant',
      content: m.content,
    })),
    { role: 'user' as const, content: message },
  ];

  // Fetch integrations from the selected pipeline
  const pipelineStack = await prisma.pipelineStack.findFirst({
    where: {
      organizationId: user.organizationId,
      ...(effectivePipelineStackId ? { id: effectivePipelineStackId } : {}),
    },
    include: {
      nodes: {
        where: { status: { notIn: ['ERROR', 'TESTING'] } },
        select: {
          id: true, name: true, toolType: true, layer: true,
          status: true, config: true,
        },
      },
    },
  });

  const validActiveStatuses = ['CONNECTED', 'HEALTHY', 'WARNING'];
  const integrations = pipelineStack?.nodes.map(node => {
    let credentials: Record<string, any> = {};
    if (node.config) {
      try {
        const configJson = node.config as { encrypted?: string; _cached?: any; [key: string]: any };
        if (configJson.encrypted) {
          const decrypted = decrypt(configJson.encrypted);
          credentials = JSON.parse(decrypted);
        } else {
          const { _cached, ...creds } = configJson;
          credentials = creds;
        }
      } catch {
        credentials = {};
      }
    }

    const config = { ...credentials };
    const toolType = node.toolType.toUpperCase();
    const usernameToUserTypes = ['SNOWFLAKE', 'POSTGRES', 'REDSHIFT'];
    if (usernameToUserTypes.includes(toolType) && config.username && !config.user) {
      config.user = config.username;
      delete config.username;
    }
    const serverToHostTypes = ['SQLSERVER', 'AZURE_SQL', 'AZURE_SYNAPSE'];
    if (serverToHostTypes.includes(toolType) && config.server && !config.host) {
      config.host = config.server;
      delete config.server;
    }
    if (toolType === 'AIRFLOW' && config.host && !config.base_url) {
      config.base_url = config.host;
      delete config.host;
    }

    // n8n: host -> base_url
    if (toolType === 'N8N' && config.host && !config.base_url) {
      config.base_url = config.host;
    }

    return {
      id: node.id,
      name: node.name,
      type: node.toolType.toUpperCase(),
      layer: node.layer.toLowerCase(),
      status: validActiveStatuses.includes(node.status) ? 'ACTIVE' : node.status,
      config,
      metadata: {},
    };
  }) || [];

  // Merge OAuth integrations
  const oauthIntegrations = await prisma.integration.findMany({
    where: { organizationId: user.organizationId, status: 'ACTIVE' },
    select: { id: true, name: true, type: true, status: true, accessToken: true, metadata: true },
  });

  for (const oauth of oauthIntegrations) {
    let accessToken = '';
    if (oauth.accessToken) {
      try { accessToken = decrypt(oauth.accessToken); } catch { /* skip */ }
    }
    const existingIdx = integrations.findIndex(i => i.type === oauth.type.toUpperCase());
    if (existingIdx >= 0) {
      integrations[existingIdx].config = {
        ...integrations[existingIdx].config,
        access_token: accessToken, token: accessToken,
      };
      integrations[existingIdx].metadata = {
        ...integrations[existingIdx].metadata,
        ...(oauth.metadata as Record<string, any> || {}),
      };
      continue;
    }
    integrations.push({
      id: oauth.id, name: oauth.name, type: oauth.type.toUpperCase(),
      layer: 'version_control',
      status: oauth.status === 'ACTIVE' ? 'ACTIVE' : oauth.status,
      config: { access_token: accessToken, token: accessToken },
      metadata: oauth.metadata as Record<string, any> || {},
    });
  }

  // Fetch lineage data
  let lineageData: { nodes: any[]; edges: any[] } = { nodes: [], edges: [] };
  try {
    const [lineageNodes, lineageEdges] = await Promise.all([
      prisma.lineageNode.findMany({
        where: { organizationId: user.organizationId },
        select: {
          id: true, name: true, database: true, schema: true, tableName: true,
          nodeType: true, description: true, upstreamCount: true, downstreamCount: true,
        },
      }),
      prisma.lineageEdge.findMany({
        where: { organizationId: user.organizationId },
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

  // Call FastAPI streaming endpoint
  const scannerResponse = await fetch(`${SCANNER_API_URL}/api/v1/copilot/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Organization-Id': user.organizationId,
    },
    body: JSON.stringify({
      message,
      messages: conversationHistory,
      session_id: chatSession.id,
      pipeline_stack_id: pipeline_stack_id || pipelineStack?.id,
      node_ids,
      referenced_entities,
      model,
      mode,
      integrations,
      lineage: lineageData,
      confirmed_tool_ids: confirmed_tool_ids || [],
      pending_tool_call: pending_tool_call || null,
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
