import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import { decrypt } from '@/lib/crypto';

// POST /api/integrations/test-connection - Test an integration connection
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const { type, config } = body;

    if (!type || !config) {
      return NextResponse.json({ error: 'Missing type or config' }, { status: 400 });
    }

    // Decrypt sensitive fields
    const decryptedConfig: Record<string, string> = {};
    for (const [key, value] of Object.entries(config)) {
      if (typeof value === 'string' && value.startsWith('enc:')) {
        decryptedConfig[key] = decrypt(value);
      } else {
        decryptedConfig[key] = value as string;
      }
    }

    const integrationType = type.toLowerCase();

    switch (integrationType) {
      // Notification integrations
      case 'slack': {
        const webhookUrl = decryptedConfig.webhook_url;
        if (!webhookUrl) {
          return NextResponse.json({ success: false, message: 'Webhook URL is required' });
        }

        try {
          // Send a test message to the Slack webhook
          const response = await fetch(webhookUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              text: '✅ Pallisade connection test successful!',
              blocks: [
                {
                  type: 'section',
                  text: {
                    type: 'mrkdwn',
                    text: '*Pallisade Connection Test*\n✅ Your Slack webhook is working correctly!',
                  },
                },
              ],
            }),
          });

          if (response.ok) {
            return NextResponse.json({ success: true, message: 'Slack webhook is working! Check your channel for a test message.' });
          } else {
            return NextResponse.json({ success: false, message: 'Invalid webhook URL or permission denied' });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to Slack' });
        }
      }

      case 'teams': {
        const webhookUrl = decryptedConfig.webhook_url;
        if (!webhookUrl) {
          return NextResponse.json({ success: false, message: 'Webhook URL is required' });
        }

        try {
          const response = await fetch(webhookUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              '@type': 'MessageCard',
              '@context': 'http://schema.org/extensions',
              summary: 'Pallisade Connection Test',
              themeColor: '00D4AA',
              title: 'Pallisade Connection Test',
              text: '✅ Your Microsoft Teams webhook is working correctly!',
            }),
          });

          if (response.ok) {
            return NextResponse.json({ success: true, message: 'Teams webhook is working! Check your channel for a test message.' });
          } else {
            return NextResponse.json({ success: false, message: 'Invalid webhook URL or permission denied' });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to Teams' });
        }
      }

      case 'pagerduty': {
        const apiKey = decryptedConfig.api_key;
        if (!apiKey) {
          return NextResponse.json({ success: false, message: 'API key is required' });
        }

        try {
          const response = await fetch('https://api.pagerduty.com/abilities', {
            headers: {
              'Authorization': `Token token=${apiKey}`,
              'Content-Type': 'application/json',
            },
          });

          if (response.ok) {
            return NextResponse.json({ success: true, message: 'PagerDuty API key is valid!' });
          } else if (response.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid API key' });
          } else {
            return NextResponse.json({ success: false, message: `PagerDuty API error: ${response.status}` });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to PagerDuty' });
        }
      }

      case 'opsgenie': {
        const apiKey = decryptedConfig.api_key;
        if (!apiKey) {
          return NextResponse.json({ success: false, message: 'API key is required' });
        }

        try {
          const response = await fetch('https://api.opsgenie.com/v2/account', {
            headers: {
              'Authorization': `GenieKey ${apiKey}`,
            },
          });

          if (response.ok) {
            const data = await response.json();
            return NextResponse.json({ success: true, message: `Connected to ${data.data?.name || 'OpsGenie'}` });
          } else if (response.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid API key' });
          } else {
            return NextResponse.json({ success: false, message: `OpsGenie API error: ${response.status}` });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to OpsGenie' });
        }
      }

      // Ticketing integrations
      case 'jira': {
        const siteUrl = decryptedConfig.site_url;
        const email = decryptedConfig.email;
        const apiToken = decryptedConfig.api_token;

        if (!siteUrl || !email || !apiToken) {
          return NextResponse.json({ success: false, message: 'Site URL, email, and API token are required' });
        }

        try {
          const credentials = Buffer.from(`${email}:${apiToken}`).toString('base64');
          const response = await fetch(`${siteUrl}/rest/api/3/myself`, {
            headers: {
              'Authorization': `Basic ${credentials}`,
              'Accept': 'application/json',
            },
          });

          if (response.ok) {
            const user = await response.json();
            return NextResponse.json({ success: true, message: `Connected as ${user.displayName}` });
          } else if (response.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid credentials' });
          } else {
            return NextResponse.json({ success: false, message: `Jira API error: ${response.status}` });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to Jira' });
        }
      }

      case 'linear': {
        const apiKey = decryptedConfig.api_key;
        if (!apiKey) {
          return NextResponse.json({ success: false, message: 'API key is required' });
        }

        try {
          const response = await fetch('https://api.linear.app/graphql', {
            method: 'POST',
            headers: {
              'Authorization': apiKey,
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              query: '{ viewer { id name } }',
            }),
          });

          if (response.ok) {
            const data = await response.json();
            if (data.data?.viewer) {
              return NextResponse.json({ success: true, message: `Connected as ${data.data.viewer.name}` });
            }
          }
          return NextResponse.json({ success: false, message: 'Invalid API key' });
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to Linear' });
        }
      }

      case 'asana': {
        const accessToken = decryptedConfig.access_token;
        if (!accessToken) {
          return NextResponse.json({ success: false, message: 'Access token is required' });
        }

        try {
          const response = await fetch('https://app.asana.com/api/1.0/users/me', {
            headers: {
              'Authorization': `Bearer ${accessToken}`,
            },
          });

          if (response.ok) {
            const data = await response.json();
            return NextResponse.json({ success: true, message: `Connected as ${data.data?.name}` });
          } else if (response.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid access token' });
          } else {
            return NextResponse.json({ success: false, message: `Asana API error: ${response.status}` });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to Asana' });
        }
      }

      case 'github_issues': {
        // This should use OAuth, but if manually configured with a token
        const accessToken = decryptedConfig.access_token;
        if (!accessToken) {
          return NextResponse.json({ success: false, message: 'Access token is required' });
        }

        try {
          const response = await fetch('https://api.github.com/user', {
            headers: {
              'Authorization': `Bearer ${accessToken}`,
              'Accept': 'application/vnd.github.v3+json',
              'User-Agent': 'Pallisade',
            },
          });

          if (response.ok) {
            const user = await response.json();
            return NextResponse.json({ success: true, message: `Connected as @${user.login}` });
          } else if (response.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid access token' });
          } else {
            return NextResponse.json({ success: false, message: `GitHub API error: ${response.status}` });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to GitHub' });
        }
      }

      // Observability integrations
      case 'monte_carlo': {
        const keyId = decryptedConfig.api_key_id;
        const keySecret = decryptedConfig.api_key_secret;

        if (!keyId || !keySecret) {
          return NextResponse.json({ success: false, message: 'API key ID and secret are required' });
        }

        try {
          const response = await fetch('https://api.getmontecarlo.com/graphql', {
            method: 'POST',
            headers: {
              'x-mcd-id': keyId,
              'x-mcd-token': keySecret,
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              query: '{ getUser { email } }',
            }),
          });

          if (response.ok) {
            const data = await response.json();
            if (data.data?.getUser) {
              return NextResponse.json({ success: true, message: `Connected to Monte Carlo` });
            }
          }
          return NextResponse.json({ success: false, message: 'Invalid API credentials' });
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to Monte Carlo' });
        }
      }

      case 'bigeye': {
        const apiKey = decryptedConfig.api_key;
        const baseUrl = decryptedConfig.base_url || 'https://app.bigeye.com';

        if (!apiKey) {
          return NextResponse.json({ success: false, message: 'API key is required' });
        }

        try {
          const response = await fetch(`${baseUrl}/api/v1/user`, {
            headers: {
              'Authorization': `Bearer ${apiKey}`,
            },
          });

          if (response.ok) {
            return NextResponse.json({ success: true, message: 'Connected to Bigeye' });
          } else if (response.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid API key' });
          } else {
            return NextResponse.json({ success: false, message: `Bigeye API error: ${response.status}` });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to Bigeye' });
        }
      }

      case 'soda': {
        const keyId = decryptedConfig.api_key_id;
        const keySecret = decryptedConfig.api_key_secret;

        if (!keyId || !keySecret) {
          return NextResponse.json({ success: false, message: 'API key ID and secret are required' });
        }

        // Soda Cloud authentication
        return NextResponse.json({ success: true, message: 'Soda credentials saved (verify with a scan)' });
      }

      case 'elementary': {
        // Elementary is dbt-native — it stores test results in the warehouse.
        // No external API key needed; the copilot will use the existing
        // warehouse connection to query Elementary tables.
        const schema = decryptedConfig.schema || 'elementary';
        return NextResponse.json({
          success: true,
          message: `Elementary configured (schema: ${schema}). Results will be read from your connected warehouse.`,
        });
      }

      default:
        return NextResponse.json({ success: false, message: `Unknown integration type: ${type}` });
    }
  } catch (error) {
    console.error('Integration test failed:', error);
    return NextResponse.json(
      { success: false, message: 'Failed to test connection' },
      { status: 500 }
    );
  }
}
