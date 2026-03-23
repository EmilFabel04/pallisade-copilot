import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const userId = (session.user as any).id;

  const accounts = await prisma.account.findMany({
    where: { userId },
    select: {
      id: true,
      provider: true,
      providerAccountId: true,
    },
  });

  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { passwordHash: true },
  });

  return NextResponse.json({
    accounts,
    hasPassword: !!user?.passwordHash,
  });
}

export async function DELETE(request: NextRequest) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const userId = (session.user as any).id;
  const { accountId } = await request.json();

  // Safety check — cannot remove last auth method
  const accountCount = await prisma.account.count({ where: { userId } });
  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { passwordHash: true },
  });

  const totalMethods = accountCount + (user?.passwordHash ? 1 : 0);

  if (totalMethods <= 1) {
    return NextResponse.json(
      { error: 'Cannot remove your only authentication method. Set a password or connect another provider first.' },
      { status: 400 }
    );
  }

  // Verify the account belongs to the user
  const account = await prisma.account.findFirst({
    where: { id: accountId, userId },
  });

  if (!account) {
    return NextResponse.json({ error: 'Account not found' }, { status: 404 });
  }

  await prisma.account.delete({ where: { id: accountId } });

  return NextResponse.json({ success: true });
}
