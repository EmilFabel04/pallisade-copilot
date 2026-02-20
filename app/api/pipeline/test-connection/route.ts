/**
 * Pipeline Test Connection API
 * 
 * Test connection to a pipeline node (warehouse, ingestion tool, etc.)
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8000';

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const { toolType, config } = body;

    // Route to appropriate test endpoint based on tool type
    let testEndpoint: string;
    let testBody: any;

    switch (toolType) {
      // Warehouse connections - use scanner's /api/v1/test-connection endpoint
      case 'snowflake':
        testEndpoint = `${SCANNER_API_URL}/api/v1/test-connection`;
        testBody = {
          connection_type: 'snowflake',
          connection_config: {
            account: config.account,
            warehouse: config.warehouse,
            database: config.database,
            schema: config.schema || 'PUBLIC',
            user: config.username,
            password: config.password,
          },
        };
        break;

      case 'bigquery':
        testEndpoint = `${SCANNER_API_URL}/api/v1/test-connection`;
        testBody = {
          connection_type: 'bigquery',
          connection_config: {
            project_id: config.project_id,
            dataset: config.dataset,
            credentials: config.credentials,
          },
        };
        break;

      case 'postgres':
        testEndpoint = `${SCANNER_API_URL}/api/v1/test-connection`;
        testBody = {
          connection_type: 'postgres',
          connection_config: {
            host: config.host,
            port: parseInt(config.port) || 5432,
            database: config.database,
            user: config.username,
            password: config.password,
            sslmode: config.ssl || 'prefer',
          },
        };
        break;

      case 'sqlserver':
      case 'azure_sql':
        testEndpoint = `${SCANNER_API_URL}/api/v1/test-connection`;
        testBody = {
          connection_type: 'sqlserver',
          connection_config: {
            host: config.server,
            port: parseInt(config.port) || 1433,
            database: config.database,
            user: config.username,
            password: config.password,
          },
        };
        break;

      case 'redshift':
        testEndpoint = `${SCANNER_API_URL}/api/v1/test-connection`;
        testBody = {
          connection_type: 'redshift',
          connection_config: {
            host: config.host,
            port: parseInt(config.port) || 5439,
            database: config.database,
            user: config.username,
            password: config.password,
            sslmode: 'require',
          },
        };
        break;

      // Ingestion tools - validate API credentials
      case 'fivetran':
        // Validate Fivetran API credentials
        try {
          const auth = Buffer.from(`${config.api_key}:${config.api_secret}`).toString('base64');
          const res = await fetch('https://api.fivetran.com/v1/groups', {
            headers: { Authorization: `Basic ${auth}` },
          });
          if (res.ok) {
            return NextResponse.json({ success: true, message: 'Connected to Fivetran successfully!' });
          } else {
            return NextResponse.json({ success: false, message: 'Invalid Fivetran credentials' });
          }
        } catch (e) {
          return NextResponse.json({ success: false, message: 'Failed to connect to Fivetran' });
        }

      case 'airbyte':
        testEndpoint = `${SCANNER_API_URL}/api/test/airbyte`;
        testBody = {
          host: config.host,
          api_key: config.api_key,
          username: config.username,
          password: config.password,
          workspace_id: config.workspace_id,
        };
        break;

      // Transformation tools
      case 'dbt_cloud':
        // Handle both Admin API and Discovery API modes
        const apiMode = config.api_mode || 'admin';
        
        if (apiMode === 'discovery') {
          // Discovery API (Metadata Only) - uses GraphQL
          if (!config.environment_id) {
            return NextResponse.json({ success: false, message: 'Environment ID is required for Discovery API mode' });
          }
          
          try {
            const discoveryResponse = await fetch('https://metadata.cloud.getdbt.com/graphql', {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${config.api_token}`,
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({
                query: `
                  query TestConnection($environmentId: BigInt!) {
                    environment(id: $environmentId) {
                      dbtProjectName
                      name
                      type
                    }
                  }
                `,
                variables: { environmentId: parseInt(config.environment_id) },
              }),
            });

            if (discoveryResponse.ok) {
              const result = await discoveryResponse.json();
              
              if (result.errors) {
                return NextResponse.json({ 
                  success: false, 
                  message: result.errors[0]?.message || 'Discovery API error - check token permissions'
                });
              }

              const env = result.data?.environment;
              if (env) {
                return NextResponse.json({
                  success: true,
                  message: `Connected to Discovery API! Project: ${env.dbtProjectName}, Environment: ${env.name}`,
                  metadata: {
                    apiMode: 'discovery',
                    projectName: env.dbtProjectName,
                    environmentName: env.name,
                    capabilities: ['lineage', 'models', 'sources', 'tests'],
                  }
                });
              }
            }

            return NextResponse.json({ success: false, message: 'Could not connect to Discovery API - verify environment ID and token' });
          } catch (e) {
            return NextResponse.json({ success: false, message: 'Failed to connect to dbt Cloud Discovery API' });
          }
        }
        
        // Admin API mode (default) - use scanner API or direct call
        if (!config.account_id) {
          return NextResponse.json({ success: false, message: 'Account ID is required for Admin API mode' });
        }
        
        try {
          // Test Admin API directly
          const adminResponse = await fetch(`https://cloud.getdbt.com/api/v2/accounts/${config.account_id}/`, {
            headers: {
              'Authorization': `Token ${config.api_token}`,
              'Accept': 'application/json',
            },
          });

          if (adminResponse.ok) {
            const data = await adminResponse.json();
            
            // Also test artifact access
            const runsResponse = await fetch(
              `https://cloud.getdbt.com/api/v2/accounts/${config.account_id}/runs/?limit=1&status=10`,
              {
                headers: {
                  'Authorization': `Token ${config.api_token}`,
                  'Accept': 'application/json',
                },
              }
            );
            
            let hasArtifactAccess = false;
            let artifactMessage = '';
            
            if (runsResponse.ok) {
              const runsData = await runsResponse.json();
              const runs = runsData.data || [];
              
              if (runs.length > 0) {
                const runId = runs[0].id;
                const artifactResponse = await fetch(
                  `https://cloud.getdbt.com/api/v2/accounts/${config.account_id}/runs/${runId}/artifacts/manifest.json`,
                  {
                    headers: {
                      'Authorization': `Token ${config.api_token}`,
                      'Accept': 'application/json',
                    },
                  }
                );
                
                hasArtifactAccess = artifactResponse.ok;
                if (!hasArtifactAccess) {
                  artifactMessage = ' (Limited permissions - no artifact access)';
                }
              }
            }

            return NextResponse.json({
              success: true,
              message: `Connected to dbt Cloud: ${data.data?.name}${artifactMessage}`,
              metadata: {
                apiMode: 'admin',
                accountName: data.data?.name,
                hasArtifactAccess,
                capabilities: hasArtifactAccess 
                  ? ['jobs', 'runs', 'artifacts', 'lineage', 'test_results']
                  : ['jobs', 'runs', 'metadata'],
              }
            });
          }

          if (adminResponse.status === 403) {
            return NextResponse.json({ 
              success: false, 
              message: 'Token lacks required permissions. Use "Job Viewer" permission set or try Discovery API mode.' 
            });
          }
          
          return NextResponse.json({ success: false, message: 'Invalid Account ID or API Token' });
        } catch (e) {
          return NextResponse.json({ success: false, message: 'Failed to connect to dbt Cloud Admin API' });
        }

      case 'dbt_core':
        // Validate dbt manifest
        if (config.manifest) {
          try {
            const manifest = JSON.parse(config.manifest);
            if (manifest.nodes && manifest.metadata) {
              const modelCount = Object.keys(manifest.nodes).filter(k => k.startsWith('model.')).length;
              return NextResponse.json({ 
                success: true, 
                message: `Manifest loaded! Found ${modelCount} models.` 
              });
            } else {
              return NextResponse.json({ success: false, message: 'Invalid manifest format' });
            }
          } catch (e) {
            return NextResponse.json({ success: false, message: 'Invalid JSON in manifest' });
          }
        }
        return NextResponse.json({ success: false, message: 'No manifest provided' });

      // Reporting tools
      case 'tableau':
        testEndpoint = `${SCANNER_API_URL}/api/test/tableau`;
        testBody = {
          server: config.server,
          token_name: config.token_name,
          token_secret: config.token_secret,
          site_id: config.site_id || '',
        };
        break;

      case 'looker':
        testEndpoint = `${SCANNER_API_URL}/api/test/looker`;
        testBody = {
          host: config.host,
          client_id: config.client_id,
          client_secret: config.client_secret,
        };
        break;

      case 'powerbi':
        testEndpoint = `${SCANNER_API_URL}/api/test/powerbi`;
        testBody = {
          tenant_id: config.tenant_id,
          client_id: config.client_id,
          client_secret: config.client_secret,
        };
        break;

      case 'metabase':
        testEndpoint = `${SCANNER_API_URL}/api/test/metabase`;
        testBody = {
          host: config.host,
          username: config.username,
          password: config.password,
          api_key: config.api_key,
        };
        break;

      // Orchestration tools - test directly
      case 'airflow': {
        try {
          const host = config.host;
          if (!host) {
            // GitHub-only mode (static DAG parsing) — no API to test
            return NextResponse.json({
              success: true,
              message: 'Airflow configured for GitHub DAG parsing (no API connection needed)'
            });
          }

          // API mode — ping the Airflow health endpoint
          const username = config.username;
          const password = config.password;
          const headers: Record<string, string> = { 'Accept': 'application/json' };
          if (username && password) {
            headers['Authorization'] = `Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`;
          }

          const healthUrl = `${host.replace(/\/$/, '')}/api/v1/health`;
          const afResponse = await fetch(healthUrl, {
            headers,
            signal: AbortSignal.timeout(10000),
          });

          if (afResponse.ok) {
            const data = await afResponse.json();
            const status = data?.metadatabase?.status || 'unknown';
            return NextResponse.json({
              success: true,
              message: `Connected to Airflow (metadb: ${status})`
            });
          } else if (afResponse.status === 401 || afResponse.status === 403) {
            return NextResponse.json({ success: false, message: 'Invalid Airflow credentials' });
          } else {
            return NextResponse.json({ success: false, message: `Airflow API error: ${afResponse.status}` });
          }
        } catch (error) {
          const msg = error instanceof Error ? error.message : 'Unknown error';
          return NextResponse.json({ success: false, message: `Failed to connect to Airflow: ${msg}` });
        }
      }

      case 'n8n': {
        try {
          const host = config.host;
          const apiKey = config.api_key;

          if (!host || !apiKey) {
            return NextResponse.json({ success: false, message: 'Instance URL and API key are required' });
          }

          const n8nUrl = `${host.replace(/\/$/, '')}/api/v1/workflows?limit=1`;
          const n8nResponse = await fetch(n8nUrl, {
            headers: {
              'X-N8N-API-KEY': apiKey,
              'Accept': 'application/json',
            },
            signal: AbortSignal.timeout(10000),
          });

          if (n8nResponse.ok) {
            return NextResponse.json({
              success: true,
              message: 'Connected to n8n successfully'
            });
          } else if (n8nResponse.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid n8n API key' });
          } else {
            return NextResponse.json({ success: false, message: `n8n API error: ${n8nResponse.status}` });
          }
        } catch (error) {
          const msg = error instanceof Error ? error.message : 'Unknown error';
          return NextResponse.json({ success: false, message: `Failed to connect to n8n: ${msg}` });
        }
      }

      // Infrastructure tools - test via scanner SSH endpoint
      case 'linux_server': {
        try {
          const serverResponse = await fetch(`${SCANNER_API_URL}/api/v1/server/test-connection`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              host: config.host,
              port: parseInt(config.port) || 22,
              username: config.username,
              auth_method: config.auth_method || 'key',
              private_key: config.private_key,
              passphrase: config.passphrase,
              password: config.password,
            }),
            signal: AbortSignal.timeout(15000),
          });

          const data = await serverResponse.json();
          if (data.success) {
            return NextResponse.json({
              success: true,
              message: data.message || `Connected to ${data.hostname} (${data.os})`,
            });
          } else {
            return NextResponse.json({
              success: false,
              message: data.message || 'SSH connection failed',
            });
          }
        } catch (error) {
          const msg = error instanceof Error ? error.message : 'Unknown error';
          return NextResponse.json({ success: false, message: `Failed to connect: ${msg}` });
        }
      }

      // Version Control tools - test directly without scanner API
      case 'github': {
        try {
          const token = config.access_token;
          if (!token) {
            return NextResponse.json({ success: false, message: 'Access token is required' });
          }

          // Test GitHub API with the token
          const ghResponse = await fetch('https://api.github.com/user', {
            headers: {
              'Authorization': `Bearer ${token}`,
              'Accept': 'application/vnd.github.v3+json',
              'User-Agent': 'Pallisade',
            },
          });

          if (ghResponse.ok) {
            const user = await ghResponse.json();
            return NextResponse.json({
              success: true,
              message: `Connected as @${user.login}`
            });
          } else if (ghResponse.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid or expired access token' });
          } else {
            return NextResponse.json({ success: false, message: `GitHub API error: ${ghResponse.status}` });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to GitHub' });
        }
      }

      case 'gitlab': {
        try {
          const token = config.access_token;
          const host = config.host || 'https://gitlab.com';

          if (!token) {
            return NextResponse.json({ success: false, message: 'Access token is required' });
          }

          // Test GitLab API with the token
          const glResponse = await fetch(`${host}/api/v4/user`, {
            headers: {
              'PRIVATE-TOKEN': token,
            },
          });

          if (glResponse.ok) {
            const user = await glResponse.json();
            return NextResponse.json({
              success: true,
              message: `Connected as @${user.username}`
            });
          } else if (glResponse.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid or expired access token' });
          } else {
            return NextResponse.json({ success: false, message: `GitLab API error: ${glResponse.status}` });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to GitLab' });
        }
      }

      case 'bitbucket': {
        try {
          const username = config.username;
          const appPassword = config.app_password;

          if (!username || !appPassword) {
            return NextResponse.json({ success: false, message: 'Username and app password are required' });
          }

          // Test Bitbucket API with basic auth
          const credentials = Buffer.from(`${username}:${appPassword}`).toString('base64');
          const bbResponse = await fetch('https://api.bitbucket.org/2.0/user', {
            headers: {
              'Authorization': `Basic ${credentials}`,
            },
          });

          if (bbResponse.ok) {
            const user = await bbResponse.json();
            return NextResponse.json({
              success: true,
              message: `Connected as ${user.display_name}`
            });
          } else if (bbResponse.status === 401) {
            return NextResponse.json({ success: false, message: 'Invalid username or app password' });
          } else {
            return NextResponse.json({ success: false, message: `Bitbucket API error: ${bbResponse.status}` });
          }
        } catch (error) {
          return NextResponse.json({ success: false, message: 'Failed to connect to Bitbucket' });
        }
      }

      default:
        return NextResponse.json({ success: false, message: `Unknown tool type: ${toolType}` });
    }

    // Make request to scanner API for warehouse tests
    const response = await fetch(testEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(testBody),
    });

    const data = await response.json();

    return NextResponse.json({
      success: data.success,
      message: data.message || (data.success ? 'Connection successful!' : 'Connection failed'),
    });
  } catch (error) {
    console.error('Connection test failed:', error);
    return NextResponse.json(
      { success: false, message: 'Failed to test connection' },
      { status: 500 }
    );
  }
}
