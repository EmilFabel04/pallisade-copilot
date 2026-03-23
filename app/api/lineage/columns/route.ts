import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

// GET /api/lineage/columns?fqn=acme-484520.public.orders&stackId=...
// Returns columns with types from the lineage engine graph for a given table FQN.
export async function GET(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const fqn = searchParams.get('fqn');
    const stackId = searchParams.get('stackId');

    if (!fqn) {
      return NextResponse.json({ error: 'fqn parameter required' }, { status: 400 });
    }

    // Fetch engine graph (which has columns on nodes)
    const params = new URLSearchParams({ plane: 'data' });
    if (stackId) params.set('stack_id', stackId);

    const res = await fetch(`${SCANNER_API_URL}/api/v1/lineage/engine/graph?${params}`, {
      signal: AbortSignal.timeout(5000),
    });

    if (!res.ok) {
      return NextResponse.json({ columns: [] });
    }

    const data = await res.json();
    const nodes = data.nodes || [];

    // Find node matching the FQN (case-insensitive, try exact and partial match)
    const fqnLower = fqn.toLowerCase();
    const matchingNode = nodes.find((n: any) => {
      const nodeFqn = (n.fqn || n.name || '').toLowerCase();
      return nodeFqn === fqnLower || nodeFqn.endsWith(fqnLower) || fqnLower.endsWith(nodeFqn);
    });

    if (!matchingNode?.columns?.length) {
      return NextResponse.json({ columns: [] });
    }

    const columns = matchingNode.columns.map((c: any) => ({
      name: c.name,
      type: c.type || c.data_type || '',
    }));

    return NextResponse.json({ columns });
  } catch (error: any) {
    console.error('[Columns] Error:', error.message);
    return NextResponse.json({ columns: [] });
  }
}
