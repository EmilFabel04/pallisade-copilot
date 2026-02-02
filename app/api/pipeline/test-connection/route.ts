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
      // Warehouse connections - use scanner API
      case 'snowflake':
        testEndpoint = `${SCANNER_API_URL}/api/test/snowflake`;
        testBody = {
          account: config.account,
          warehouse: config.warehouse,
          database: config.database,
          schema: config.schema || 'PUBLIC',
          user: config.username,  // Map from form field name
          password: config.password,
        };
        break;
      
      case 'bigquery':
        testEndpoint = `${SCANNER_API_URL}/api/test/bigquery`;
        testBody = {
          project: config.project_id,  // Map from form field name
          dataset: config.dataset,
          credentials: config.credentials,  // This is the uploaded JSON content
        };
        break;
      
      case 'postgres':
        testEndpoint = `${SCANNER_API_URL}/api/test/postgres`;
        testBody = {
          host: config.host,
          port: parseInt(config.port) || 5432,
          database: config.database,
          user: config.username,  // Map from form field name
          password: config.password,
          sslmode: config.ssl || 'prefer',
        };
        break;
      
      case 'sqlserver':
      case 'azure_sql':
        testEndpoint = `${SCANNER_API_URL}/api/test/sqlserver`;
        testBody = {
          host: config.server,
          port: parseInt(config.port) || 1433,
          database: config.database,
          user: config.username,  // Map from form field name
          password: config.password,
        };
        break;
      
      case 'redshift':
        testEndpoint = `${SCANNER_API_URL}/api/test/postgres`;  // Redshift uses postgres protocol
        testBody = {
          host: config.host,
          port: parseInt(config.port) || 5439,
          database: config.database,
          user: config.username,  // Map from form field name
          password: config.password,
          sslmode: 'require',  // Redshift requires SSL
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
        testEndpoint = `${SCANNER_API_URL}/api/test/dbt_cloud`;
        testBody = {
          api_key: config.api_key,
          account_id: parseInt(config.account_id),
        };
        break;

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
