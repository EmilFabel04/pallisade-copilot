/**
 * Pipeline Test Connection API
 * 
 * Test connection to a pipeline node (warehouse, ingestion tool, etc.)
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';

const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8080';

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
