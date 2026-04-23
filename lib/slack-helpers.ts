/**
 * Shared Slack helpers for org-level config and client creation.
 * Centralizes the pattern of: find integration → decrypt bot token → return typed config.
 */

import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { SlackClient } from '@/lib/integrations/slack';

export interface SlackPreferences {
  alertOnCritical: boolean;
  alertOnHigh: boolean;
  alertOnScanComplete: boolean;
  alertOnPrCreated: boolean;
  alertOnTeamInvite: boolean;
}

export interface SlackOrgConfig {
  connected: boolean;
  botToken: string | null;
  channel: string | null;
  teamName: string | null;
  preferences: SlackPreferences;
}

const DEFAULT_PREFERENCES: SlackPreferences = {
  alertOnCritical: true,
  alertOnHigh: true,
  alertOnScanComplete: false,
  alertOnPrCreated: true,
  alertOnTeamInvite: true,
};

/**
 * Fetch the Slack integration config for an organization.
 * Returns a typed object with connection status and notification preferences.
 */
export async function getSlackOrgConfig(organizationId: string): Promise<SlackOrgConfig> {
  try {
    const integration = await prisma.integration.findFirst({
      where: { organizationId, type: 'SLACK' },
    });

    if (!integration || integration.status !== 'ACTIVE') {
      return { connected: false, botToken: null, channel: null, teamName: null, preferences: DEFAULT_PREFERENCES };
    }

    // Decrypt the bot token from accessToken field
    let botToken: string | null = null;
    if (integration.accessToken) {
      try {
        botToken = decrypt(integration.accessToken);
      } catch {
        console.error('[Slack] Failed to decrypt bot token');
      }
    }

    const creds = typeof integration.credentials === 'string'
      ? JSON.parse(integration.credentials)
      : (integration.credentials as Record<string, any>) || {};

    const metadata = (integration.metadata as Record<string, any>) || {};

    return {
      connected: !!botToken,
      botToken,
      channel: creds.channel || null,
      teamName: metadata.teamName || metadata.team || null,
      preferences: {
        alertOnCritical: creds.alertOnCritical ?? true,
        alertOnHigh: creds.alertOnHigh ?? true,
        alertOnScanComplete: creds.alertOnScanComplete ?? false,
        alertOnPrCreated: creds.alertOnPrCreated ?? true,
        alertOnTeamInvite: creds.alertOnTeamInvite ?? true,
      },
    };
  } catch (error) {
    console.error('[Slack] Failed to fetch org config:', error);
    return { connected: false, botToken: null, channel: null, teamName: null, preferences: DEFAULT_PREFERENCES };
  }
}

/**
 * Get a ready-to-use SlackClient for an organization.
 * Returns null if Slack is not connected.
 */
export async function getSlackClient(
  organizationId: string,
  channelOverride?: string,
): Promise<SlackClient | null> {
  const config = await getSlackOrgConfig(organizationId);
  if (!config.connected || !config.botToken) return null;

  return new SlackClient({
    bot_token: config.botToken,
    channel: channelOverride || config.channel || undefined,
  });
}
