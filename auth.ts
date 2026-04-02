import NextAuth from 'next-auth';
import { PrismaAdapter } from '@auth/prisma-adapter';
import Credentials from 'next-auth/providers/credentials';
import Google from 'next-auth/providers/google';
import GitHub from 'next-auth/providers/github';
import MicrosoftEntraID from 'next-auth/providers/microsoft-entra-id';
import bcrypt from 'bcryptjs';
import prisma from '@/lib/db';

export const { auth, handlers, signIn, signOut } = NextAuth({
  adapter: PrismaAdapter(prisma),
  session: { strategy: 'jwt' },
  pages: {
    signIn: '/login',
    error: '/login',
  },
  providers: [
    Credentials({
      name: 'credentials',
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) {
          throw new Error('Email and password are required');
        }

        const user = await prisma.user.findUnique({
          where: { email: credentials.email as string },
          include: { organization: true },
        });

        if (!user || !user.passwordHash) {
          throw new Error('Invalid email or password');
        }

        const isValid = await bcrypt.compare(
          credentials.password as string,
          user.passwordHash
        );
        if (!isValid) {
          throw new Error('Invalid email or password');
        }

        return {
          id: user.id,
          email: user.email,
          name: user.name,
          image: user.image,
          organizationId: user.organizationId,
          timezone: user.timezone,
        };
      },
    }),

    // Google OAuth (optional)
    ...(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET
      ? [Google({
          clientId: process.env.GOOGLE_CLIENT_ID,
          clientSecret: process.env.GOOGLE_CLIENT_SECRET,
        })]
      : []),

    // GitHub OAuth (optional)
    ...(process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET
      ? [GitHub({
          clientId: process.env.GITHUB_CLIENT_ID,
          clientSecret: process.env.GITHUB_CLIENT_SECRET,
        })]
      : []),

    // Microsoft Entra ID (optional)
    ...(process.env.MICROSOFT_CLIENT_ID && process.env.MICROSOFT_CLIENT_SECRET
      ? [MicrosoftEntraID({
          clientId: process.env.MICROSOFT_CLIENT_ID,
          clientSecret: process.env.MICROSOFT_CLIENT_SECRET,
          issuer: `https://login.microsoftonline.com/${process.env.MICROSOFT_TENANT_ID || 'common'}/v2.0`,
        })]
      : []),
  ],
  callbacks: {
    async signIn({ user, account, profile }) {
      // Credentials provider — check SSO enforcement before allowing
      if (account?.provider === 'credentials') {
        const dbUser = await prisma.user.findUnique({
          where: { id: user.id! },
          include: { organization: true },
        });

        // Check SSO enforcement for the user's org
        if (dbUser?.organization?.authPolicy === 'SSO_ONLY') {
          const graceUntil = dbUser.organization.authPolicyGraceUntil;
          if (!graceUntil || new Date() > graceUntil) {
            return '/login?error=SSORequired';
          }
        }

        // If user has no org, check for a pending invite (covers existing users
        // who were invited after creating their account)
        if (!dbUser?.organizationId && dbUser?.email) {
          const invite = await prisma.teamInvite.findFirst({
            where: {
              email: dbUser.email,
              status: 'PENDING',
              expiresAt: { gt: new Date() },
            },
          });

          if (invite) {
            await prisma.$transaction(async (tx) => {
              await tx.teamMember.create({
                data: {
                  userId: dbUser.id,
                  organizationId: invite.organizationId,
                  role: invite.role,
                  status: 'ACTIVE',
                  joinedAt: new Date(),
                },
              });
              await tx.user.update({
                where: { id: dbUser.id },
                data: { organizationId: invite.organizationId },
              });
              await tx.teamInvite.update({
                where: { id: invite.id },
                data: { status: 'ACCEPTED', respondedAt: new Date() },
              });

              // Grant pipeline access — VIEWER on all org pipelines
              const orgPipelines = await tx.pipelineStack.findMany({
                where: { organizationId: invite.organizationId },
                select: { id: true },
              });
              for (const pipeline of orgPipelines) {
                await tx.pipelineAccess.upsert({
                  where: {
                    userId_pipelineId: {
                      userId: dbUser.id,
                      pipelineId: pipeline.id,
                    },
                  },
                  create: {
                    userId: dbUser.id,
                    pipelineId: pipeline.id,
                    accessLevel: 'VIEWER',
                    grantedBy: invite.invitedById || dbUser.id,
                  },
                  update: {},
                });
              }
            });
          }
        }

        return true;
      }

      // OAuth provider — check if user already exists with an org
      const email = user.email;
      if (!email) return false;

      const existingUser = await prisma.user.findUnique({
        where: { email },
        include: { organization: true },
      });

      if (existingUser?.organizationId) {
        // Existing user with org — always allow OAuth sign-in
        return true;
      }

      // New user or existing user without org — check for invite
      const invite = await prisma.teamInvite.findFirst({
        where: {
          email,
          status: 'PENDING',
          expiresAt: { gt: new Date() },
        },
        include: { organization: true },
      });

      if (invite) {
        // Verify email is verified by the OAuth provider
        const emailVerified = (profile as any)?.email_verified;
        if (emailVerified !== true && account?.provider !== 'credentials') {
          return '/login?error=UnverifiedEmail';
        }

        // Redeem invite in a transaction
        const userId = (existingUser?.id || user.id) as string;
        await prisma.$transaction(async (tx) => {
          await tx.teamMember.create({
            data: {
              userId,
              organizationId: invite.organizationId,
              role: invite.role,
              status: 'ACTIVE',
              joinedAt: new Date(),
            },
          });
          await tx.user.update({
            where: { id: userId },
            data: { organizationId: invite.organizationId },
          });
          await tx.teamInvite.update({
            where: { id: invite.id },
            data: { status: 'ACCEPTED', respondedAt: new Date() },
          });

          // Grant pipeline access — VIEWER on all org pipelines
          const orgPipelines = await tx.pipelineStack.findMany({
            where: { organizationId: invite.organizationId },
            select: { id: true },
          });
          for (const pipeline of orgPipelines) {
            await tx.pipelineAccess.upsert({
              where: {
                userId_pipelineId: {
                  userId,
                  pipelineId: pipeline.id,
                },
              },
              create: {
                userId,
                pipelineId: pipeline.id,
                accessLevel: 'VIEWER',
                grantedBy: invite.invitedById || userId,
              },
              update: {},
            });
          }
        });
      }

      // Allow sign-in — users without an invite go through
      // onboarding to create their own organization (same as password signup)
      return true;
    },

    async jwt({ token, user, trigger }) {
      if (user) {
        token.id = user.id;
        token.organizationId = (user as any).organizationId;
        token.timezone = (user as any).timezone;
      }

      // On first OAuth sign-in, re-fetch org from DB
      // (signIn callback may have set organizationId after user was created)
      if (trigger === 'signIn' && token.id) {
        const dbUser = await prisma.user.findUnique({
          where: { id: token.id as string },
          select: { organizationId: true, timezone: true },
        });
        if (dbUser) {
          token.organizationId = dbUser.organizationId;
          token.timezone = dbUser.timezone;
        }
      }

      // Re-fetch from DB when client calls useSession().update()
      if (trigger === 'update' && token.id) {
        const dbUser = await prisma.user.findUnique({
          where: { id: token.id as string },
          select: { timezone: true, organizationId: true },
        });
        if (dbUser) {
          token.timezone = dbUser.timezone;
          token.organizationId = dbUser.organizationId;
        }
      }

      return token;
    },

    async session({ session, token }) {
      if (session.user) {
        (session.user as any).id = token.id;
        (session.user as any).organizationId = token.organizationId;
        (session.user as any).timezone = token.timezone;
      }
      return session;
    },
  },
});
