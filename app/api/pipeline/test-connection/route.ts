/**
 * Pipeline Test Connection API
 * 
 * Test connection to a pipeline node (warehouse, ingestion tool, etc.)
 */

import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { scannerClient } from '@/lib/scanner-client';
import { assertExternalUrl } from '@/lib/net/safe-url';

/**
 * Resolve the GitHub access token from the GitHub connector node in the same stack.
 * Used by dbt/airflow nodes that reference repos from the GitHub connector.
 */
async function resolveGitHubToken(stackId: string | undefined, organizationId: string): Promise<string | null> {
  if (!stackId) return null;
  try {
    const githubNode = await prisma.pipelineNode.findFirst({
      where: { stackId, toolType: 'github', stack: { organizationId } },
      include: { integration: true },
    });
    if (!githubNode) return null;

    let config: Record<string, any> = {};
    if ((githubNode as any).integrationId && (githubNode as any).integration?.credentials) {
      const intCreds = (githubNode as any).integration.credentials as any;
      config = intCreds.encrypted ? JSON.parse(decrypt(intCreds.encrypted)) : intCreds;
    } else if (githubNode.config) {
      const configJson = githubNode.config as any;
      config = configJson.encrypted ? JSON.parse(decrypt(configJson.encrypted)) : configJson;
    }
    return config.access_token || null;
  } catch {
    return null;
  }
}

export async function POST(request: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ success: false, message: 'Please sign in to test connections' }, { status: 401 });
    }
    if (!(session.user as any).organizationId) {
      return NextResponse.json({ success: false, message: 'No organization found — try signing out and back in' }, { status: 401 });
    }

    const body = await request.json();
    const { toolType, config, stackId } = body;
    const organizationId = (session.user as any).organizationId;

    // Route to appropriate test endpoint based on tool type
    let scannerPath: string;
    let testBody: any;

    switch (toolType) {
      // Warehouse connections - use scanner's /api/v1/test-connection endpoint
      case 'snowflake':
        scannerPath = '/api/v1/test-connection';
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
        scannerPath = '/api/v1/test-connection';
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
        scannerPath = '/api/v1/test-connection';
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
        scannerPath = '/api/v1/test-connection';
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
        scannerPath = '/api/v1/test-connection';
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

      case 'airbyte': {
        let abHost = (config.host || '').replace(/\/+$/, '');
        if (!abHost) {
          return NextResponse.json({ success: false, message: 'Airbyte host URL is required' });
        }

        // Auto-correct common mistake: user enters the dashboard URL instead of the API URL
        if (abHost.includes('cloud.airbyte.com') && !abHost.includes('api.airbyte.com')) {
          abHost = 'https://api.airbyte.com';
        }

        const isCloud = abHost.includes('api.airbyte.com') || abHost.includes('airbyte.com');

        try {
          if (isCloud) {
            // Airbyte Cloud uses client credentials → short-lived Bearer token
            const clientId = config.client_id;
            const clientSecret = config.client_secret;

            if (!clientId || !clientSecret) {
              return NextResponse.json({
                success: false,
                message: 'Client ID and Client Secret are required for Airbyte Cloud. Create an Application in Settings → Applications.',
              });
            }

            // Step 1: Exchange client credentials for access token
            const tokenRes = await fetch(`${abHost}/v1/applications/token`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                client_id: clientId,
                client_secret: clientSecret,
                grant_type: 'client_credentials',
              }),
              signal: AbortSignal.timeout(10000),
            });

            if (!tokenRes.ok) {
              const errText = await tokenRes.text().catch(() => '');
              if (tokenRes.status === 401 || tokenRes.status === 403) {
                return NextResponse.json({ success: false, message: 'Invalid Client ID or Client Secret. Check Settings → Applications in Airbyte Cloud.' });
              }
              return NextResponse.json({ success: false, message: `Token exchange failed (${tokenRes.status}): ${errText}` });
            }

            const tokenData = await tokenRes.json();
            const accessToken = tokenData.access_token;
            if (!accessToken) {
              return NextResponse.json({ success: false, message: 'Token exchange succeeded but no access_token returned' });
            }

            // Step 2: Use the token to verify workspace access
            const abHeaders: Record<string, string> = {
              'Authorization': `Bearer ${accessToken}`,
              'Accept': 'application/json',
            };

            const abUrl = config.workspace_id
              ? `${abHost}/v1/workspaces/${config.workspace_id}`
              : `${abHost}/v1/workspaces`;
            const abRes = await fetch(abUrl, {
              headers: abHeaders,
              signal: AbortSignal.timeout(10000),
            });

            const contentType = abRes.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
              return NextResponse.json({ success: false, message: 'The host URL returned an HTML page instead of JSON. Use https://api.airbyte.com as the host.' });
            }

            if (abRes.ok) {
              const abData = await abRes.json();
              if (config.workspace_id) {
                const wsName = abData.name || config.workspace_id;
                return NextResponse.json({ success: true, message: `Connected to Airbyte Cloud workspace: ${wsName}` });
              }
              const count = abData.data?.length ?? 0;
              return NextResponse.json({ success: true, message: `Connected to Airbyte Cloud (${count} workspace${count !== 1 ? 's' : ''})` });
            } else if (abRes.status === 401 || abRes.status === 403) {
              return NextResponse.json({ success: false, message: 'Token valid but insufficient permissions for this workspace' });
            } else {
              return NextResponse.json({ success: false, message: `Airbyte Cloud API error: ${abRes.status}` });
            }
          } else {
            // Airbyte OSS — hit health endpoint, then optionally list workspaces
            const abHeaders: Record<string, string> = { 'Accept': 'application/json' };
            if (config.username && config.password) {
              abHeaders['Authorization'] = `Basic ${Buffer.from(`${config.username}:${config.password}`).toString('base64')}`;
            }

            const healthRes = await fetch(`${abHost}/api/v1/health`, {
              headers: { 'Accept': 'application/json' },
              signal: AbortSignal.timeout(10000),
            });

            const healthCt = healthRes.headers.get('content-type') || '';
            if (!healthRes.ok || !healthCt.includes('application/json')) {
              return NextResponse.json({ success: false, message: `Cannot reach Airbyte API at ${abHost}. Make sure this is the Airbyte API URL, not the web UI.` });
            }

            // If workspace_id provided, verify it exists
            if (config.workspace_id) {
              const wsRes = await fetch(`${abHost}/api/v1/workspaces/get`, {
                method: 'POST',
                headers: { ...abHeaders, 'Content-Type': 'application/json' },
                body: JSON.stringify({ workspaceId: config.workspace_id }),
                signal: AbortSignal.timeout(10000),
              });
              if (wsRes.ok) {
                const wsData = await wsRes.json();
                return NextResponse.json({ success: true, message: `Connected to Airbyte OSS workspace: ${wsData.name || config.workspace_id}` });
              }
            }

            return NextResponse.json({ success: true, message: 'Connected to Airbyte OSS' });
          }
        } catch (error) {
          const msg = error instanceof Error ? error.message : 'Unknown error';
          return NextResponse.json({ success: false, message: `Failed to connect to Airbyte: ${msg}` });
        }
      }

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

      case 'dbt_core': {
        const sourceMode = config.source_mode || 'upload';

        // Mode 1: Upload manifest.json directly
        if (sourceMode === 'upload') {
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
                return NextResponse.json({ success: false, message: 'Invalid manifest format — missing nodes or metadata' });
              }
            } catch (e) {
              return NextResponse.json({ success: false, message: 'Invalid JSON in manifest' });
            }
          }
          return NextResponse.json({ success: false, message: 'No manifest file uploaded. Upload your manifest.json from the target/ folder.' });
        }

        // Mode 2: Upload dbt project folder (SQL + YAML files)
        if (sourceMode === 'project') {
          const projectFiles = config.project_files;
          if (!projectFiles || typeof projectFiles !== 'object' || Object.keys(projectFiles).length === 0) {
            return NextResponse.json({ success: false, message: 'No project files uploaded. Select your dbt project folder.' });
          }
          const fileCount = Object.keys(projectFiles).length;
          const hasDbtProject = Object.keys(projectFiles).some(f => f.endsWith('dbt_project.yml'));
          const sqlFiles = Object.keys(projectFiles).filter(f => f.endsWith('.sql'));
          const ymlFiles = Object.keys(projectFiles).filter(f => f.endsWith('.yml') || f.endsWith('.yaml'));

          if (!hasDbtProject) {
            return NextResponse.json({
              success: false,
              message: `Found ${fileCount} files but no dbt_project.yml. Make sure you selected the correct dbt project folder.`
            });
          }

          return NextResponse.json({
            success: true,
            message: `Project loaded! Found ${sqlFiles.length} SQL models and ${ymlFiles.length} YAML configs.`
          });
        }

        // Mode 3: GitHub repository
        if (sourceMode === 'github') {
          const repo = config.github_repo;
          if (!repo) {
            return NextResponse.json({ success: false, message: 'No GitHub repository specified.' });
          }

          // Validate repo format
          if (!repo.includes('/')) {
            return NextResponse.json({ success: false, message: 'Repository should be in "owner/repo" format.' });
          }

          // Try to fetch the repo to validate access
          const branch = config.github_branch || 'main';
          const token = config.github_token || await resolveGitHubToken(stackId, organizationId) || '';
          const headers: Record<string, string> = { 'Accept': 'application/vnd.github.v3+json' };
          if (token) {
            headers['Authorization'] = `Bearer ${token}`;
          }

          try {
            // Check repo exists and is accessible
            const repoRes = await fetch(`https://api.github.com/repos/${repo}`, { headers });

            if (repoRes.status === 404) {
              return NextResponse.json({ success: false, message: `Repository "${repo}" not found. Check the name or add a GitHub token for private repos.` });
            }
            if (repoRes.status === 401 || repoRes.status === 403) {
              return NextResponse.json({ success: false, message: 'GitHub authentication failed. Check your token.' });
            }
            if (!repoRes.ok) {
              return NextResponse.json({ success: false, message: `GitHub API error: ${repoRes.status}` });
            }

            // Check for dbt_project.yml in the repo
            const dbtPath = config.dbt_project_path ? `${config.dbt_project_path}/dbt_project.yml` : 'dbt_project.yml';
            const fileRes = await fetch(`https://api.github.com/repos/${repo}/contents/${dbtPath}?ref=${branch}`, { headers });

            if (fileRes.ok) {
              const repoData = await repoRes.json();
              return NextResponse.json({
                success: true,
                message: `Connected to ${repo} (${branch}). Found dbt_project.yml.`
              });
            } else {
              return NextResponse.json({
                success: false,
                message: `Connected to repo but dbt_project.yml not found at "${dbtPath}" on branch "${branch}".`
              });
            }
          } catch (e) {
            return NextResponse.json({ success: false, message: 'Failed to connect to GitHub. Check your network and try again.' });
          }
        }

        return NextResponse.json({ success: false, message: 'Unknown source mode. Select Upload, Project, or GitHub.' });
      }

      // Reporting tools
      case 'tableau':
        scannerPath = '/api/test/tableau';
        testBody = {
          server: config.server,
          token_name: config.token_name,
          token_secret: config.token_secret,
          site_id: config.site_id || '',
        };
        break;

      case 'looker':
        scannerPath = '/api/test/looker';
        testBody = {
          host: config.host,
          client_id: config.client_id,
          client_secret: config.client_secret,
        };
        break;

      case 'powerbi':
        scannerPath = '/api/test/powerbi';
        testBody = {
          tenant_id: config.tenant_id,
          client_id: config.client_id,
          client_secret: config.client_secret,
        };
        break;

      case 'metabase': {
        // Test Metabase connection directly via its API
        const mbHost = (config.host || '').replace(/\/+$/, '');
        const mbApiKey = config.api_key;
        if (!mbHost || !mbApiKey) {
          return NextResponse.json({ success: false, message: 'Metabase URL and API Key are required' });
        }
        try {
          const mbRes = await fetch(`${mbHost}/api/user/current`, {
            method: 'GET',
            headers: { 'X-Api-Key': mbApiKey },
          });
          if (mbRes.ok) {
            const mbUser = await mbRes.json();
            const name = mbUser.common_name || mbUser.email || 'Unknown';
            return NextResponse.json({ success: true, message: `Connected as ${name}` });
          }
          const mbErr = await mbRes.text();
          return NextResponse.json({ success: false, message: `Metabase returned ${mbRes.status}: ${mbErr}` });
        } catch (e) {
          return NextResponse.json({ success: false, message: `Failed to connect to Metabase: ${e instanceof Error ? e.message : 'Network error'}` });
        }
      }

      // Orchestration tools - test directly
      case 'airflow': {
        try {
          const host = config.host;
          const sourceMode = config.source_mode || (host ? 'api' : 'github');

          if (sourceMode === 'github') {
            // GitHub mode — verify we can list the DAG directory
            const repo = config.github_repo;
            const token = config.github_token || await resolveGitHubToken(stackId, organizationId) || '';
            const branch = config.github_branch || 'main';
            const dagDir = config.dag_directory || 'dags';

            if (!repo) {
              return NextResponse.json({ success: false, message: 'GitHub repo is required for DAG file parsing' });
            }
            if (!token) {
              return NextResponse.json({ success: false, message: 'No GitHub token found. Configure a GitHub connector first.' });
            }

            const ghResponse = await fetch(
              `https://api.github.com/repos/${repo}/contents/${dagDir}?ref=${branch}`,
              {
                headers: {
                  Authorization: `token ${token}`,
                  Accept: 'application/vnd.github.v3+json',
                },
                signal: AbortSignal.timeout(10000),
              }
            );

            if (ghResponse.ok) {
              const items = await ghResponse.json();
              const pyFiles = Array.isArray(items) ? items.filter((i: any) => i.name?.endsWith('.py')).length : 0;
              return NextResponse.json({
                success: true,
                message: `Found ${pyFiles} DAG files in ${repo}/${dagDir}`
              });
            } else if (ghResponse.status === 404) {
              return NextResponse.json({ success: false, message: `DAG directory "${dagDir}" not found in ${repo} (branch: ${branch})` });
            } else {
              return NextResponse.json({ success: false, message: `GitHub API error: ${ghResponse.status}` });
            }
          }

          if (!host) {
            return NextResponse.json({ success: false, message: 'Airflow host URL is required for API mode' });
          }

          // API mode — two-step test:
          // 1) Health endpoint (usually public) to verify URL is correct
          // 2) Authenticated endpoint (/dags) to verify credentials work
          const username = config.username;
          const password = config.password;
          const cleanHost = host.replace(/\/+$/, '');

          // Step 1: Health check (no auth needed on most setups)
          const healthResponse = await fetch(`${cleanHost}/api/v1/health`, {
            headers: { 'Accept': 'application/json' },
            signal: AbortSignal.timeout(10000),
          });

          if (!healthResponse.ok) {
            return NextResponse.json({
              success: false,
              message: `Cannot reach Airflow at ${cleanHost} (HTTP ${healthResponse.status}). Verify the URL is correct and Airflow is running.`,
            });
          }

          // Step 2: Test an authenticated endpoint to verify credentials
          if (!username || !password) {
            // No credentials — health passed, warn about auth
            return NextResponse.json({
              success: true,
              message: 'Airflow is reachable but no credentials provided. API calls requiring auth will fail.',
            });
          }

          const auth = `Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`;
          const dagsResponse = await fetch(`${cleanHost}/api/v1/dags?limit=1`, {
            headers: {
              'Authorization': auth,
              'Accept': 'application/json',
            },
            signal: AbortSignal.timeout(10000),
          });

          if (dagsResponse.ok) {
            const data = await dagsResponse.json();
            const dagCount = data.total_entries ?? data.dags?.length ?? 0;
            return NextResponse.json({
              success: true,
              message: `Connected to Airflow (${dagCount} DAG${dagCount !== 1 ? 's' : ''} found)`,
            });
          }

          if (dagsResponse.status === 401 || dagsResponse.status === 403) {
            return NextResponse.json({
              success: false,
              message:
                'Airflow is reachable but rejected authentication (HTTP ' + dagsResponse.status + '). ' +
                'Check your username/password. If using Airflow 2.x, ensure the REST API auth backend is enabled: ' +
                'set AIRFLOW__API__AUTH_BACKENDS=airflow.api.auth.backend.basic_auth in your Airflow environment.',
            });
          }

          return NextResponse.json({
            success: false,
            message: `Airflow API returned HTTP ${dagsResponse.status}. Check Airflow logs for details.`,
          });
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
          const serverResponse = await scannerClient.fetch(session, '/api/v1/server/test-connection', {
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
          let glUrl: URL;
          try {
            glUrl = await assertExternalUrl(`${host}/api/v4/user`);
          } catch (e) {
            return NextResponse.json({
              success: false,
              message: `Invalid GitLab host: ${e instanceof Error ? e.message : 'not allowed'}`,
            });
          }
          const glResponse = await fetch(glUrl, {
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
    const response = await scannerClient.fetch(session, scannerPath, {
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
