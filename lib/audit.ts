/**
 * Audit Logging Utility
 * 
 * Use this to log important events throughout the application.
 * 
 * Usage:
 *   import { logAudit } from '@/lib/audit';
 *   
 *   await logAudit({
 *     action: 'scan.started',
 *     category: 'scan',
 *     description: 'Started freshness scan',
 *     userId: user.id,
 *     userEmail: user.email,
 *     userName: user.name,
 *     resourceType: 'Report',
 *     resourceId: reportId,
 *     organizationId: orgId,
 *   });
 */

import prisma from '@/lib/db';

export interface AuditLogParams {
  action: string;
  category: 'scan' | 'integration' | 'user' | 'schedule' | 'settings' | 'incident' | 'contract';
  description: string;
  userId?: string;
  userEmail?: string;
  userName?: string;
  resourceType?: string;
  resourceId?: string;
  resourceName?: string;
  metadata?: Record<string, any>;
  status?: 'success' | 'failure' | 'pending';
  errorMessage?: string;
  organizationId?: string;
  ipAddress?: string;
  userAgent?: string;
}

/**
 * Create an audit log entry
 */
export async function logAudit(params: AuditLogParams): Promise<void> {
  try {
    await prisma.auditLog.create({
      data: {
        action: params.action,
        category: params.category,
        description: params.description,
        userId: params.userId,
        userEmail: params.userEmail,
        userName: params.userName,
        resourceType: params.resourceType,
        resourceId: params.resourceId,
        resourceName: params.resourceName,
        metadata: params.metadata || undefined,
        status: params.status || 'success',
        errorMessage: params.errorMessage,
        organizationId: params.organizationId,
        ipAddress: params.ipAddress,
        userAgent: params.userAgent,
      },
    });
  } catch (error) {
    // Don't throw - audit logging shouldn't break the main flow
    console.error('Failed to create audit log:', error);
  }
}

/**
 * Helper for common audit events
 */
export const auditEvents = {
  // Scan events
  scanStarted: (userId: string | undefined, userEmail: string | undefined, userName: string | undefined, scanType: string, organizationId: string | undefined) => 
    logAudit({
      action: 'scan.started',
      category: 'scan',
      description: `Started ${scanType} scan`,
      userId,
      userEmail,
      userName,
      resourceType: 'Scan',
      resourceName: scanType,
      organizationId,
    }),
    
  scanCompleted: (userId: string | undefined, userEmail: string | undefined, userName: string | undefined, scanType: string, reportId: string, score: number, organizationId: string | undefined) =>
    logAudit({
      action: 'scan.completed',
      category: 'scan',
      description: `Completed ${scanType} scan with score ${score}`,
      userId,
      userEmail,
      userName,
      resourceType: 'Report',
      resourceId: reportId,
      resourceName: scanType,
      metadata: { score },
      organizationId,
    }),
    
  scanFailed: (userId: string | undefined, userEmail: string | undefined, userName: string | undefined, scanType: string, error: string, organizationId: string | undefined) =>
    logAudit({
      action: 'scan.failed',
      category: 'scan',
      description: `Failed ${scanType} scan: ${error}`,
      userId,
      userEmail,
      userName,
      resourceType: 'Scan',
      resourceName: scanType,
      status: 'failure',
      errorMessage: error,
      organizationId,
    }),

  // Integration events
  integrationCreated: (userId: string | undefined, userEmail: string | undefined, userName: string | undefined, integrationType: string, integrationName: string, integrationId: string, organizationId: string | undefined) =>
    logAudit({
      action: 'integration.created',
      category: 'integration',
      description: `Connected ${integrationType} integration: ${integrationName}`,
      userId,
      userEmail,
      userName,
      resourceType: 'Integration',
      resourceId: integrationId,
      resourceName: integrationName,
      metadata: { type: integrationType },
      organizationId,
    }),
    
  integrationDeleted: (userId: string | undefined, userEmail: string | undefined, userName: string | undefined, integrationName: string, organizationId: string | undefined) =>
    logAudit({
      action: 'integration.deleted',
      category: 'integration',
      description: `Removed integration: ${integrationName}`,
      userId,
      userEmail,
      userName,
      resourceType: 'Integration',
      resourceName: integrationName,
      organizationId,
    }),

  // User events
  userLogin: (userId: string, userEmail: string, userName: string | undefined, organizationId: string | undefined, ipAddress?: string) =>
    logAudit({
      action: 'user.login',
      category: 'user',
      description: `User logged in: ${userEmail}`,
      userId,
      userEmail,
      userName,
      organizationId,
      ipAddress,
    }),
    
  userLogout: (userId: string, userEmail: string, userName: string | undefined, organizationId: string | undefined) =>
    logAudit({
      action: 'user.logout',
      category: 'user',
      description: `User logged out: ${userEmail}`,
      userId,
      userEmail,
      userName,
      organizationId,
    }),

  // Schedule events
  scheduleCreated: (userId: string | undefined, userEmail: string | undefined, userName: string | undefined, scheduleName: string, scheduleId: string, organizationId: string | undefined) =>
    logAudit({
      action: 'schedule.created',
      category: 'schedule',
      description: `Created schedule: ${scheduleName}`,
      userId,
      userEmail,
      userName,
      resourceType: 'Schedule',
      resourceId: scheduleId,
      resourceName: scheduleName,
      organizationId,
    }),
    
  scheduleTriggered: (scheduleName: string, scheduleId: string, organizationId: string | undefined) =>
    logAudit({
      action: 'schedule.triggered',
      category: 'schedule',
      description: `Triggered scheduled scan: ${scheduleName}`,
      resourceType: 'Schedule',
      resourceId: scheduleId,
      resourceName: scheduleName,
      organizationId,
    }),
};

