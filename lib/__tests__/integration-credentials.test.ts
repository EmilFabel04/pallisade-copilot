/**
 * Tests for resolveStackIntegrations — specifically the OAuth-merge step,
 * which had a clobber bug: the merge unconditionally overwrote
 * config.access_token with Integration.accessToken, which is empty for
 * PAT-based integrations. This destroyed real PATs every request.
 */

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    pipelineStack: { findFirst: jest.fn() },
    integration: { findMany: jest.fn() },
  },
}));

jest.mock('@/lib/crypto', () => ({
  __esModule: true,
  decrypt: jest.fn((s: string) => {
    // Strip a "enc:" prefix used by these tests; otherwise pass through
    if (typeof s === 'string' && s.startsWith('enc:')) return s.slice(4);
    return s;
  }),
  encrypt: jest.fn((s: string) => `enc:${s}`),
  hash: jest.fn((s: string) => `hash:${s}`),
}));

import prisma from '@/lib/db';
import { resolveStackIntegrations } from '@/lib/integration-credentials';

const mockedPrisma = prisma as unknown as {
  pipelineStack: { findFirst: jest.Mock };
  integration: { findMany: jest.Mock };
};

beforeEach(() => {
  mockedPrisma.pipelineStack.findFirst.mockReset();
  mockedPrisma.integration.findMany.mockReset();
});

function makeGithubPipelineNode(opts: {
  pat: string;
  status?: string;
  integrationAccessToken?: string | null;
}) {
  const credentialsJson = JSON.stringify({
    access_token: opts.pat,
    owner: 'EmilFabel04',
    repos: ['EmilFabel04/pallisade-test-pipeline'],
  });
  return {
    id: 'node_gh',
    name: 'GitHub',
    toolType: 'GITHUB',
    layer: 'VERSION_CONTROL',
    status: opts.status ?? 'CONNECTED',
    integrationId: 'int_gh',
    integration: {
      // resolveStackIntegrations decrypts via decryptIntegrationCredentials
      credentials: { encrypted: `enc:${credentialsJson}` },
    },
    config: null,
  };
}

describe('resolveStackIntegrations — OAuth merge does not clobber existing PATs', () => {
  test('PAT pasted in pipeline form survives the merge step', async () => {
    mockedPrisma.pipelineStack.findFirst.mockResolvedValue({
      id: 'stack_1',
      organizationId: 'org_1',
      nodes: [
        makeGithubPipelineNode({
          pat: 'ghp_real_user_PAT',
          integrationAccessToken: null, // OAuth field NOT populated for PAT flow
        }),
      ],
    });
    // Step 2 returns the SAME Integration row, with accessToken=null
    // (because the user pasted a PAT — never went through OAuth).
    mockedPrisma.integration.findMany.mockResolvedValue([
      {
        id: 'int_gh',
        name: 'GitHub',
        type: 'GITHUB',
        status: 'ACTIVE',
        accessToken: null,
        metadata: null,
      },
    ]);

    const integrations = await resolveStackIntegrations('stack_1', 'org_1');

    const gh = integrations.find((i) => i.type === 'GITHUB');
    expect(gh).toBeDefined();
    expect(gh!.config.access_token).toBe('ghp_real_user_PAT');
    // 'token' alias should NOT be set to an empty string overwriting a real value
    if ('token' in gh!.config) {
      expect(gh!.config.token).not.toBe('');
    }
  });

  test('OAuth token IS used when pipeline node has no access_token of its own', async () => {
    // Edge case: future OAuth-flow GitHub integration where the pipeline
    // node legitimately has no PAT and the merge is the *correct* source.
    const credentialsJson = JSON.stringify({ owner: 'acme' }); // no access_token
    mockedPrisma.pipelineStack.findFirst.mockResolvedValue({
      id: 'stack_1',
      organizationId: 'org_1',
      nodes: [
        {
          id: 'node_gh',
          name: 'GitHub',
          toolType: 'GITHUB',
          layer: 'VERSION_CONTROL',
          status: 'CONNECTED',
          integrationId: 'int_gh',
          integration: { credentials: { encrypted: `enc:${credentialsJson}` } },
          config: null,
        },
      ],
    });
    mockedPrisma.integration.findMany.mockResolvedValue([
      {
        id: 'int_gh',
        name: 'GitHub',
        type: 'GITHUB',
        status: 'ACTIVE',
        accessToken: 'enc:ghu_oauth_flow_token',
        metadata: null,
      },
    ]);

    const integrations = await resolveStackIntegrations('stack_1', 'org_1');

    const gh = integrations.find((i) => i.type === 'GITHUB');
    expect(gh).toBeDefined();
    expect(gh!.config.access_token).toBe('ghu_oauth_flow_token');
  });

  test('non-GitHub integrations do not get spurious access_token/token keys injected', async () => {
    // The bug fired for every type, polluting integrations like LINUX_SERVER
    // with empty access_token/token keys they never had.
    const linuxCreds = JSON.stringify({
      host: '10.0.0.1',
      port: 22,
      username: 'ec2-user',
      auth_method: 'password',
      password: 'secret',
    });
    mockedPrisma.pipelineStack.findFirst.mockResolvedValue({
      id: 'stack_1',
      organizationId: 'org_1',
      nodes: [
        {
          id: 'node_lx',
          name: 'Linux Server',
          toolType: 'LINUX_SERVER',
          layer: 'INFRASTRUCTURE',
          status: 'CONNECTED',
          integrationId: 'int_lx',
          integration: { credentials: { encrypted: `enc:${linuxCreds}` } },
          config: null,
        },
      ],
    });
    mockedPrisma.integration.findMany.mockResolvedValue([
      {
        id: 'int_lx',
        name: 'Linux Server',
        type: 'LINUX_SERVER',
        status: 'ACTIVE',
        accessToken: null, // never an OAuth integration
        metadata: null,
      },
    ]);

    const integrations = await resolveStackIntegrations('stack_1', 'org_1');

    const lx = integrations.find((i) => i.type === 'LINUX_SERVER');
    expect(lx).toBeDefined();
    expect(lx!.config.access_token).toBeUndefined();
    expect(lx!.config.token).toBeUndefined();
    expect(lx!.config.host).toBe('10.0.0.1');
    expect(lx!.config.password).toBe('secret');
  });

  test('PAT stays intact even when Integration row has empty-string accessToken', async () => {
    // Defensive: some legacy rows store '' rather than NULL.
    mockedPrisma.pipelineStack.findFirst.mockResolvedValue({
      id: 'stack_1',
      organizationId: 'org_1',
      nodes: [
        makeGithubPipelineNode({
          pat: 'ghp_pat_must_survive',
          integrationAccessToken: '',
        }),
      ],
    });
    mockedPrisma.integration.findMany.mockResolvedValue([
      {
        id: 'int_gh',
        name: 'GitHub',
        type: 'GITHUB',
        status: 'ACTIVE',
        accessToken: '', // empty string — not NULL
        metadata: null,
      },
    ]);

    const integrations = await resolveStackIntegrations('stack_1', 'org_1');
    const gh = integrations.find((i) => i.type === 'GITHUB');
    expect(gh!.config.access_token).toBe('ghp_pat_must_survive');
  });
});
