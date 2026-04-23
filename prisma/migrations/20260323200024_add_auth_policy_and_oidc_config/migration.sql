-- CreateEnum
CREATE TYPE "AuthPolicy" AS ENUM ('FLEXIBLE', 'SSO_ONLY');

-- AlterEnum
ALTER TYPE "MonitorKind" ADD VALUE 'AI_PROMPT';

-- AlterTable
ALTER TABLE "Monitor" ADD COLUMN     "policyOverrides" TEXT[];

-- AlterTable
ALTER TABLE "Organization" ADD COLUMN     "authPolicy" "AuthPolicy" NOT NULL DEFAULT 'FLEXIBLE',
ADD COLUMN     "authPolicyGraceUntil" TIMESTAMP(3);

-- CreateTable
CREATE TABLE "OrgOidcConfig" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "issuerUrl" TEXT NOT NULL,
    "clientId" TEXT NOT NULL,
    "clientSecret" TEXT NOT NULL,
    "scopes" TEXT NOT NULL DEFAULT 'openid email profile',
    "displayName" TEXT NOT NULL DEFAULT 'SSO',
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "OrgOidcConfig_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "OrgOidcConfig_organizationId_key" ON "OrgOidcConfig"("organizationId");

-- AddForeignKey
ALTER TABLE "OrgOidcConfig" ADD CONSTRAINT "OrgOidcConfig_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;
