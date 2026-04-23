-- CreateTable
CREATE TABLE "NotificationRoute" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "severity" "NotificationSeverity" NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "notifyOnRecovery" BOOLEAN NOT NULL DEFAULT false,
    "destinations" JSONB NOT NULL DEFAULT '[]',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "NotificationRoute_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "NotificationMute" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "eventType" TEXT NOT NULL,
    "entityType" TEXT,
    "entityId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "NotificationMute_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "NotificationRoute_organizationId_severity_key" ON "NotificationRoute"("organizationId", "severity");

-- CreateIndex
CREATE INDEX "NotificationRoute_organizationId_idx" ON "NotificationRoute"("organizationId");

-- CreateIndex
CREATE INDEX "NotificationMute_organizationId_userId_idx" ON "NotificationMute"("organizationId", "userId");

-- CreateIndex
CREATE INDEX "NotificationMute_eventType_entityType_entityId_idx" ON "NotificationMute"("eventType", "entityType", "entityId");

-- AddForeignKey
ALTER TABLE "NotificationRoute" ADD CONSTRAINT "NotificationRoute_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "NotificationMute" ADD CONSTRAINT "NotificationMute_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "Organization"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "NotificationMute" ADD CONSTRAINT "NotificationMute_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;
