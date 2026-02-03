import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';

// POST /api/integrations/test - Test credentials before creating integration
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const { type, credentials, config } = body;

    if (!type) {
      return NextResponse.json({ error: 'Integration type is required' }, { status: 400 });
    }

    const result = await testConnection(type, credentials, config);
    return NextResponse.json(result);
  } catch (error) {
    console.error('Error testing connection:', error);
    return NextResponse.json({ 
      success: false, 
      error: 'Failed to test connection' 
    }, { status: 500 });
  }
}

// Test connection implementations
async function testConnection(
  type: string, 
  credentials: any, 
  config: any
): Promise<{ success: boolean; error?: string; metadata?: any }> {
  switch (type) {
    case 'SNOWFLAKE':
      return testSnowflake(credentials);
    case 'SQLSERVER':
    case 'AZURE_SQL':
    case 'AZURE_SYNAPSE':
      return testSqlServer(credentials, type);
    case 'AZURE_DATA_FACTORY':
      return testAzureDataFactory(credentials);
    case 'POSTGRES':
      return testPostgres(credentials);
    case 'MYSQL':
      return testMysql(credentials);
    case 'GITHUB':
      return testGitHub(credentials);
    case 'DBT_CLOUD':
      return testDbtCloud(credentials);
    case 'AIRFLOW':
      return testAirflow(credentials);
    case 'SLACK':
      return testSlack(credentials);
    default:
      // For unsupported types, just validate we have some credentials
      if (credentials && Object.keys(credentials).length > 0) {
        return { success: true, metadata: { type } };
      }
      return { success: false, error: `Credentials required for ${type}` };
  }
}

async function testSnowflake(credentials: any): Promise<{ success: boolean; error?: string; message?: string; metadata?: any }> {
  // Validate required fields first
  if (!credentials?.account || !credentials?.user || !credentials?.password) {
    return { success: false, error: 'Missing required: account, user, password' };
  }
  if (!credentials?.warehouse) {
    return { success: false, error: 'Missing required: warehouse' };
  }
  if (!credentials?.database) {
    return { success: false, error: 'Missing required: database' };
  }

  // Try to actually connect via the Python backend
  const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8080';
  
  try {
    // First check if scanner backend is available
    const healthCheck = await fetch(`${SCANNER_API_URL}/health`, { 
      method: 'GET',
      signal: AbortSignal.timeout(3000)
    });
    
    if (!healthCheck.ok) {
      // Backend not available - do basic validation only
      console.log('[TEST] Scanner backend not available, using basic validation');
      return { 
        success: true, 
        message: 'Credentials validated (backend offline - full test skipped)',
        metadata: { 
          account: credentials.account,
          database: credentials.database,
          warehouse: credentials.warehouse,
        } 
      };
    }

    // Call the Python backend to test the actual connection
    const testResponse = await fetch(`${SCANNER_API_URL}/api/test/snowflake`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account: credentials.account,
        user: credentials.user,
        password: credentials.password,
        warehouse: credentials.warehouse,
        database: credentials.database,
        schema: credentials.schema || 'PUBLIC',
        role: credentials.role || 'PUBLIC',
      }),
      signal: AbortSignal.timeout(15000), // 15s timeout for connection
    });

    if (testResponse.ok) {
      const result = await testResponse.json();
      return { 
        success: true,
        message: result.message || 'Successfully connected to Snowflake!',
        metadata: { 
          account: credentials.account,
          database: credentials.database,
          warehouse: credentials.warehouse,
          tables: result.tables,
        } 
      };
    } else {
      const errorData = await testResponse.json().catch(() => ({}));
      return { 
        success: false, 
        error: errorData.detail || errorData.error || 'Failed to connect to Snowflake' 
      };
    }
  } catch (error: any) {
    // If backend call fails, check if it's a timeout or network error
    if (error.name === 'TimeoutError' || error.name === 'AbortError') {
      return { 
        success: false, 
        error: 'Connection test timed out. Check your account identifier and network.' 
      };
    }
    
    // Backend might not have the test endpoint - fall back to basic validation
    console.log('[TEST] Backend test failed, using basic validation:', error.message);
    return { 
      success: true, 
      message: 'Credentials look valid (could not verify connection)',
      metadata: { 
        account: credentials.account,
        database: credentials.database,
        warehouse: credentials.warehouse,
      } 
    };
  }
}

async function testGitHub(credentials: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  const token = credentials?.access_token || credentials?.token;
  if (!token) {
    return { success: false, error: 'Missing GitHub token' };
  }

  try {
    const response = await fetch('https://api.github.com/user', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Pallisade',
      },
    });

    if (response.ok) {
      const user = await response.json();
      
      // Fetch repos
      const reposResponse = await fetch('https://api.github.com/user/repos?per_page=100&sort=updated', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/vnd.github.v3+json',
          'User-Agent': 'Pallisade',
        },
      });
      
      let repos: any[] = [];
      if (reposResponse.ok) {
        repos = await reposResponse.json();
      }

      return { 
        success: true, 
        metadata: { 
          username: user.login,
          name: user.name,
          avatar: user.avatar_url,
          repos: repos.map((r: any) => ({
            name: r.full_name,
            private: r.private,
            url: r.html_url,
          })),
          repoCount: repos.length,
        } 
      };
    }

    const error = await response.json();
    return { success: false, error: error.message || 'Invalid token' };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

async function testDbtCloud(credentials: any): Promise<{ success: boolean; error?: string; message?: string; metadata?: any }> {
  const accountId = credentials?.account_id;
  const token = credentials?.api_token;
  const environmentId = credentials?.environment_id;
  const useDiscoveryApi = credentials?.use_discovery_api || false;

  if (!accountId && !environmentId) {
    return { success: false, error: 'Missing dbt Cloud Account ID or Environment ID' };
  }
  if (!token) {
    return { success: false, error: 'Missing dbt Cloud API Token' };
  }

  try {
    // If using Discovery API (Metadata API) - requires environment_id
    if (useDiscoveryApi && environmentId) {
      const discoveryResponse = await fetch('https://metadata.cloud.getdbt.com/graphql', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
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
          variables: { environmentId: parseInt(environmentId) },
        }),
      });

      if (discoveryResponse.ok) {
        const result = await discoveryResponse.json();
        
        if (result.errors) {
          return { 
            success: false, 
            error: result.errors[0]?.message || 'Discovery API error - check token permissions' 
          };
        }

        const env = result.data?.environment;
        if (env) {
          return {
            success: true,
            message: 'Connected via Discovery API (Metadata Only)',
            metadata: {
              apiMode: 'discovery',
              projectName: env.dbtProjectName,
              environmentName: env.name,
              environmentType: env.type,
              environmentId,
              capabilities: ['lineage', 'models', 'sources', 'tests', 'exposures'],
              limitations: ['No run history', 'No artifacts', 'No job management'],
            }
          };
        }
      }

      return { success: false, error: 'Could not connect to Discovery API - verify environment ID and token permissions' };
    }

    // Use Admin API v2 (requires "Job Viewer" or higher permissions)
    const response = await fetch(`https://cloud.getdbt.com/api/v2/accounts/${accountId}/`, {
      headers: {
        'Authorization': `Token ${token}`,
        'Accept': 'application/json',
      },
    });

    if (response.ok) {
      const data = await response.json();
      
      // Fetch projects
      const projectsResponse = await fetch(`https://cloud.getdbt.com/api/v2/accounts/${accountId}/projects/`, {
        headers: {
          'Authorization': `Token ${token}`,
          'Accept': 'application/json',
        },
      });

      let projects: any[] = [];
      if (projectsResponse.ok) {
        const projectsData = await projectsResponse.json();
        projects = projectsData.data || [];
      }

      // Test artifact access (to verify full permissions)
      let hasArtifactAccess = false;
      let artifactWarning = '';
      
      // Try to get a recent run to test artifact permissions
      const runsResponse = await fetch(
        `https://cloud.getdbt.com/api/v2/accounts/${accountId}/runs/?limit=1&status=10`,
        {
          headers: {
            'Authorization': `Token ${token}`,
            'Accept': 'application/json',
          },
        }
      );
      
      if (runsResponse.ok) {
        const runsData = await runsResponse.json();
        const runs = runsData.data || [];
        
        if (runs.length > 0) {
          const runId = runs[0].id;
          const artifactResponse = await fetch(
            `https://cloud.getdbt.com/api/v2/accounts/${accountId}/runs/${runId}/artifacts/manifest.json`,
            {
              headers: {
                'Authorization': `Token ${token}`,
                'Accept': 'application/json',
              },
            }
          );
          
          hasArtifactAccess = artifactResponse.ok;
          if (!hasArtifactAccess) {
            artifactWarning = 'Token lacks artifact access - consider using "Job Viewer" permission set for full functionality';
          }
        }
      }

      return { 
        success: true,
        message: hasArtifactAccess 
          ? 'Connected via Admin API with full access'
          : 'Connected via Admin API (limited permissions)',
        metadata: { 
          apiMode: 'admin',
          accountName: data.data?.name,
          accountId,
          projects: projects.map((p: any) => ({ id: p.id, name: p.name })),
          projectCount: projects.length,
          hasArtifactAccess,
          warning: artifactWarning || undefined,
          capabilities: hasArtifactAccess 
            ? ['jobs', 'runs', 'artifacts', 'lineage', 'test_results']
            : ['jobs', 'runs', 'metadata'],
        } 
      };
    }

    // Check if it's a 403 (permission denied) vs 401 (invalid token)
    if (response.status === 403) {
      return { 
        success: false, 
        error: 'Token lacks required permissions. Use a service token with "Job Viewer" or "Account Viewer" permission set.' 
      };
    }
    
    return { success: false, error: 'Invalid Account ID or API Token' };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

async function testAirflow(credentials: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  const baseUrl = credentials?.base_url;
  
  if (!baseUrl) {
    return { success: false, error: 'Missing Airflow base URL' };
  }

  try {
    const auth = credentials?.username && credentials?.password 
      ? `Basic ${Buffer.from(`${credentials.username}:${credentials.password}`).toString('base64')}`
      : undefined;

    const response = await fetch(`${baseUrl}/api/v1/health`, {
      headers: auth ? { 'Authorization': auth } : {},
    });

    if (response.ok) {
      return { 
        success: true, 
        metadata: { baseUrl } 
      };
    }

    return { success: false, error: 'Could not connect to Airflow' };
  } catch (error: any) {
    return { success: false, error: `Connection failed: ${error.message}` };
  }
}

async function testSlack(credentials: any): Promise<{ success: boolean; error?: string; metadata?: any }> {
  const token = credentials?.bot_token;
  
  if (!token) {
    return { success: false, error: 'Missing Slack Bot Token' };
  }

  try {
    const response = await fetch('https://slack.com/api/auth.test', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    });

    const data = await response.json();

    if (data.ok) {
      return { 
        success: true, 
        metadata: { 
          team: data.team,
          teamId: data.team_id,
          botUserId: data.user_id,
        } 
      };
    }

    return { success: false, error: data.error || 'Invalid token' };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// SQL Server / Azure SQL / Azure Synapse connection test
async function testSqlServer(credentials: any, type: string): Promise<{ success: boolean; error?: string; message?: string; metadata?: any }> {
  if (!credentials?.host) {
    return { success: false, error: 'Missing required: server host' };
  }
  if (!credentials?.database) {
    return { success: false, error: 'Missing required: database' };
  }
  if (!credentials?.user) {
    return { success: false, error: 'Missing required: username' };
  }
  if (!credentials?.password) {
    return { success: false, error: 'Missing required: password' };
  }

  const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8080';
  
  try {
    // Check if scanner backend is available
    const healthCheck = await fetch(`${SCANNER_API_URL}/health`, { 
      method: 'GET',
      signal: AbortSignal.timeout(3000)
    });
    
    if (!healthCheck.ok) {
      console.log('[TEST] Scanner backend not available, using basic validation');
      return { 
        success: true, 
        message: `Credentials validated (backend offline - full ${type} test skipped)`,
        metadata: { 
          host: credentials.host,
          database: credentials.database,
          type,
        } 
      };
    }

    // Call the Python backend to test the actual connection
    const testResponse = await fetch(`${SCANNER_API_URL}/api/test/sqlserver`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: credentials.host,
        port: credentials.port || 1433,
        user: credentials.user,
        password: credentials.password,
        database: credentials.database,
        encrypt: type !== 'SQLSERVER', // Azure requires encryption
        driver: '{ODBC Driver 18 for SQL Server}',
      }),
      signal: AbortSignal.timeout(15000),
    });

    if (testResponse.ok) {
      const result = await testResponse.json();
      return { 
        success: true,
        message: result.message || `Successfully connected to ${type}!`,
        metadata: { 
          host: credentials.host,
          database: credentials.database,
          type,
          tables: result.tables,
        } 
      };
    } else {
      const errorData = await testResponse.json().catch(() => ({}));
      return { 
        success: false, 
        error: errorData.detail || errorData.error || `Failed to connect to ${type}` 
      };
    }
  } catch (error: any) {
    if (error.name === 'TimeoutError' || error.name === 'AbortError') {
      return { 
        success: false, 
        error: 'Connection test timed out. Check your server address and network.' 
      };
    }
    
    console.log('[TEST] Backend test failed, using basic validation:', error.message);
    return { 
      success: true, 
      message: `Credentials look valid for ${type} (could not verify connection)`,
      metadata: { 
        host: credentials.host,
        database: credentials.database,
        type,
      } 
    };
  }
}

// Azure Data Factory connection test
async function testAzureDataFactory(credentials: any): Promise<{ success: boolean; error?: string; message?: string; metadata?: any }> {
  if (!credentials?.subscription_id) {
    return { success: false, error: 'Missing required: Subscription ID' };
  }
  if (!credentials?.resource_group) {
    return { success: false, error: 'Missing required: Resource Group' };
  }
  if (!credentials?.factory_name) {
    return { success: false, error: 'Missing required: Factory Name' };
  }
  if (!credentials?.tenant_id) {
    return { success: false, error: 'Missing required: Tenant ID' };
  }
  if (!credentials?.client_id) {
    return { success: false, error: 'Missing required: Client ID' };
  }
  if (!credentials?.client_secret) {
    return { success: false, error: 'Missing required: Client Secret' };
  }

  try {
    // Get Azure AD token
    const tokenResponse = await fetch(
      `https://login.microsoftonline.com/${credentials.tenant_id}/oauth2/v2.0/token`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          client_id: credentials.client_id,
          client_secret: credentials.client_secret,
          scope: 'https://management.azure.com/.default',
          grant_type: 'client_credentials',
        }),
      }
    );

    if (!tokenResponse.ok) {
      const error = await tokenResponse.json().catch(() => ({}));
      return { 
        success: false, 
        error: error.error_description || 'Failed to authenticate with Azure AD' 
      };
    }

    const tokenData = await tokenResponse.json();
    const accessToken = tokenData.access_token;

    // Test ADF API
    const adfResponse = await fetch(
      `https://management.azure.com/subscriptions/${credentials.subscription_id}/resourceGroups/${credentials.resource_group}/providers/Microsoft.DataFactory/factories/${credentials.factory_name}?api-version=2018-06-01`,
      {
        headers: { 'Authorization': `Bearer ${accessToken}` },
      }
    );

    if (adfResponse.ok) {
      const adfData = await adfResponse.json();
      
      // Get pipelines
      const pipelinesResponse = await fetch(
        `https://management.azure.com/subscriptions/${credentials.subscription_id}/resourceGroups/${credentials.resource_group}/providers/Microsoft.DataFactory/factories/${credentials.factory_name}/pipelines?api-version=2018-06-01`,
        {
          headers: { 'Authorization': `Bearer ${accessToken}` },
        }
      );

      let pipelines: any[] = [];
      if (pipelinesResponse.ok) {
        const pipelinesData = await pipelinesResponse.json();
        pipelines = pipelinesData.value || [];
      }

      return { 
        success: true,
        message: 'Successfully connected to Azure Data Factory!',
        metadata: { 
          factoryName: adfData.name,
          location: adfData.location,
          provisioningState: adfData.properties?.provisioningState,
          pipelines: pipelines.map((p: any) => p.name),
          pipelineCount: pipelines.length,
        } 
      };
    }

    const error = await adfResponse.json().catch(() => ({}));
    return { 
      success: false, 
      error: error.error?.message || 'Failed to access Data Factory' 
    };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// PostgreSQL connection test
async function testPostgres(credentials: any): Promise<{ success: boolean; error?: string; message?: string; metadata?: any }> {
  if (!credentials?.host) {
    return { success: false, error: 'Missing required: host' };
  }
  if (!credentials?.database) {
    return { success: false, error: 'Missing required: database' };
  }
  if (!credentials?.user) {
    return { success: false, error: 'Missing required: username' };
  }
  if (!credentials?.password) {
    return { success: false, error: 'Missing required: password' };
  }

  const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8080';
  
  try {
    const healthCheck = await fetch(`${SCANNER_API_URL}/health`, { 
      method: 'GET',
      signal: AbortSignal.timeout(3000)
    });
    
    if (!healthCheck.ok) {
      return { 
        success: true, 
        message: 'Credentials validated (backend offline - full test skipped)',
        metadata: { 
          host: credentials.host,
          database: credentials.database,
        } 
      };
    }

    const testResponse = await fetch(`${SCANNER_API_URL}/api/test/postgres`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: credentials.host,
        port: credentials.port || 5432,
        user: credentials.user,
        password: credentials.password,
        database: credentials.database,
        sslmode: credentials.sslmode || 'prefer',
      }),
      signal: AbortSignal.timeout(15000),
    });

    if (testResponse.ok) {
      const result = await testResponse.json();
      return { 
        success: true,
        message: result.message || 'Successfully connected to PostgreSQL!',
        metadata: { 
          host: credentials.host,
          database: credentials.database,
          tables: result.tables,
        } 
      };
    } else {
      const errorData = await testResponse.json().catch(() => ({}));
      return { 
        success: false, 
        error: errorData.detail || errorData.error || 'Failed to connect to PostgreSQL' 
      };
    }
  } catch (error: any) {
    return { 
      success: true, 
      message: 'Credentials look valid (could not verify connection)',
      metadata: { 
        host: credentials.host,
        database: credentials.database,
      } 
    };
  }
}

// MySQL connection test
async function testMysql(credentials: any): Promise<{ success: boolean; error?: string; message?: string; metadata?: any }> {
  if (!credentials?.host) {
    return { success: false, error: 'Missing required: host' };
  }
  if (!credentials?.database) {
    return { success: false, error: 'Missing required: database' };
  }
  if (!credentials?.user) {
    return { success: false, error: 'Missing required: username' };
  }
  if (!credentials?.password) {
    return { success: false, error: 'Missing required: password' };
  }

  const SCANNER_API_URL = process.env.SCANNER_API_URL || 'http://127.0.0.1:8080';
  
  try {
    const healthCheck = await fetch(`${SCANNER_API_URL}/health`, { 
      method: 'GET',
      signal: AbortSignal.timeout(3000)
    });
    
    if (!healthCheck.ok) {
      return { 
        success: true, 
        message: 'Credentials validated (backend offline - full test skipped)',
        metadata: { 
          host: credentials.host,
          database: credentials.database,
        } 
      };
    }

    const testResponse = await fetch(`${SCANNER_API_URL}/api/test/mysql`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: credentials.host,
        port: credentials.port || 3306,
        user: credentials.user,
        password: credentials.password,
        database: credentials.database,
      }),
      signal: AbortSignal.timeout(15000),
    });

    if (testResponse.ok) {
      const result = await testResponse.json();
      return { 
        success: true,
        message: result.message || 'Successfully connected to MySQL!',
        metadata: { 
          host: credentials.host,
          database: credentials.database,
          tables: result.tables,
        } 
      };
    } else {
      const errorData = await testResponse.json().catch(() => ({}));
      return { 
        success: false, 
        error: errorData.detail || errorData.error || 'Failed to connect to MySQL' 
      };
    }
  } catch (error: any) {
    return { 
      success: true, 
      message: 'Credentials look valid (could not verify connection)',
      metadata: { 
        host: credentials.host,
        database: credentials.database,
      } 
    };
  }
}

