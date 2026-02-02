import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

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
    const { message, session_id, pipeline_stack_id, node_ids, model = 'claude-sonnet' } = body;

    if (!message) {
      return NextResponse.json({ error: 'Message required' }, { status: 400 });
    }

    // Fetch pipeline nodes (integrations) from the database
    const pipelineStack = await prisma.pipelineStack.findFirst({
      where: { organizationId: user.organizationId },
      include: {
        nodes: {
          where: { status: 'CONNECTED' },
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

    // Convert pipeline nodes to integration format for the scanner
    // Note: type must be uppercase to match the scanner's tool registry
    const integrations = pipelineStack?.nodes.map(node => ({
      id: node.id,
      name: node.name,
      type: node.toolType.toUpperCase(), // Scanner expects BIGQUERY, SNOWFLAKE, etc.
      layer: node.layer.toLowerCase(),
      status: node.status === 'CONNECTED' ? 'ACTIVE' : node.status,
      config: node.config || {},
    })) || [];
    
    console.log('[COPILOT] Sending integrations to scanner:', integrations.map(i => ({ name: i.name, type: i.type, status: i.status })));

    // Call the scanner copilot API
    const response = await fetch(`${SCANNER_API_URL}/api/v1/copilot/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Organization-Id': user.organizationId,
      },
      body: JSON.stringify({
        message,
        session_id,
        pipeline_stack_id: pipeline_stack_id || pipelineStack?.id,
        node_ids,
        model,
        integrations, // Pass integrations from pipeline nodes
      }),
    });

    if (!response.ok) {
      // If scanner API is not available, return a helpful message
      const errorText = await response.text();
      console.error('Scanner API error:', errorText);
      
      return NextResponse.json({
        session_id: session_id || 'local',
        message: getLocalFallbackResponse(message),
        tool_calls: [],
        input_tokens: 0,
        output_tokens: 0,
      });
    }

    const data = await response.json();
    return NextResponse.json(data);

  } catch (error) {
    console.error('Copilot chat error:', error);
    
    // Return a local fallback response
    const body = await request.clone().json().catch(() => ({}));
    return NextResponse.json({
      session_id: body.session_id || 'local',
      message: getLocalFallbackResponse(body.message || ''),
      tool_calls: [],
      input_tokens: 0,
      output_tokens: 0,
    });
  }
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
