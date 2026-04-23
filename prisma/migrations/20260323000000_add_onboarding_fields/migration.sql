-- AlterTable
ALTER TABLE "User" ADD COLUMN "timezone" TEXT,
ADD COLUMN "role" TEXT,
ADD COLUMN "onboardingCompleted" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN "onboardingStep" INTEGER NOT NULL DEFAULT 0;

-- AlterTable
ALTER TABLE "Organization" ADD COLUMN "companySize" TEXT,
ADD COLUMN "industry" TEXT,
ADD COLUMN "dataTeamSize" TEXT;

-- Backfill existing users so they are not locked out
UPDATE "User" SET "onboardingCompleted" = true, "onboardingStep" = 4, "timezone" = 'UTC' WHERE "onboardingCompleted" = false;
