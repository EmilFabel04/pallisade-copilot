import { NextResponse } from 'next/server';

const SCANNER_URL = process.env.SCANNER_URL || 'http://localhost:8000';

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ type: string }> },
) {
  const { type } = await params;
  const url = `${SCANNER_URL}/api/v1/drivers/${type}`;
  try {
    const resp = await fetch(url, { cache: 'no-store' });
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch {
    return NextResponse.json(
      { error: `Failed to fetch driver ${type}` },
      { status: 502 },
    );
  }
}
