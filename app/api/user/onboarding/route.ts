import { NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const userId = (session.user as any).id;
  const body = await request.json();
  const { step, completed } = body;

  // Validate step is forward-only
  const current = await prisma.user.findUnique({
    where: { id: userId },
    select: { onboardingStep: true },
  });

  if (typeof step !== 'number' || step < (current?.onboardingStep ?? 0)) {
    return NextResponse.json({ error: 'Invalid step' }, { status: 400 });
  }

  const data: Record<string, any> = { onboardingStep: step };
  if (completed) {
    data.onboardingCompleted = true;
  }

  const user = await prisma.user.update({
    where: { id: userId },
    data,
    select: { id: true, onboardingStep: true, onboardingCompleted: true },
  });

  return NextResponse.json({ user });
}

export async function GET(request: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const user = await prisma.user.findUnique({
    where: { id: (session.user as any).id },
    select: { onboardingStep: true, onboardingCompleted: true },
  });

  return NextResponse.json({ user });
}
