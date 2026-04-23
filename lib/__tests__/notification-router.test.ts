const mockFindUnique = jest.fn();
const mockFindMany = jest.fn();
const mockSlackSendMessage = jest.fn().mockResolvedValue(undefined);
const mockPdCreateIncident = jest.fn().mockResolvedValue({ dedup_key: 'dk' });
const mockTeamsSendMessage = jest.fn().mockResolvedValue(undefined);
const mockOgCreateAlert = jest.fn().mockResolvedValue({ requestId: 'r1' });
const mockEmailSend = jest.fn().mockResolvedValue(undefined);

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    notificationRoute: { findUnique: (...args: any[]) => mockFindUnique(...args) },
    integration: { findMany: (...args: any[]) => mockFindMany(...args) },
  },
}));
jest.mock('@/lib/crypto', () => ({ decrypt: jest.fn((v: string) => v) }));
jest.mock('@/lib/integrations/slack', () => ({
  SlackClient: jest.fn().mockImplementation(() => ({ sendMessage: mockSlackSendMessage })),
}));
jest.mock('@/lib/integrations/pagerduty', () => ({
  PagerDutyClient: jest.fn().mockImplementation(() => ({ createIncident: mockPdCreateIncident })),
}));
jest.mock('@/lib/integrations/teams', () => ({
  TeamsClient: jest.fn().mockImplementation(() => ({ sendMessage: mockTeamsSendMessage })),
}));
jest.mock('@/lib/integrations/opsgenie', () => ({
  OpsgenieClient: jest.fn().mockImplementation(() => ({ createAlert: mockOgCreateAlert })),
}));
jest.mock('@/lib/integrations/email', () => ({
  EmailClient: jest.fn().mockImplementation(() => ({ sendEmail: mockEmailSend })),
}));

import { routeNotification } from '../notification-router';

describe('routeNotification', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should dispatch to Slack when route has Slack destination', async () => {
    mockFindUnique.mockResolvedValue({
      enabled: true, notifyOnRecovery: false,
      destinations: [{ integrationId: 'int1', channel: '#alerts' }],
    });
    mockFindMany.mockResolvedValue([
      { id: 'int1', type: 'SLACK', status: 'ACTIVE', accessToken: 'xoxb-test', credentials: '{}', config: {} },
    ]);

    await routeNotification({ organizationId: 'org1', severity: 'ERROR', title: 'Test Alert', message: 'Something failed' });
    expect(mockSlackSendMessage).toHaveBeenCalled();
  });

  it('should dispatch to PagerDuty when route has PagerDuty destination', async () => {
    mockFindUnique.mockResolvedValue({
      enabled: true, notifyOnRecovery: false,
      destinations: [{ integrationId: 'int2', config: { routing_key: 'rk-test' } }],
    });
    mockFindMany.mockResolvedValue([
      { id: 'int2', type: 'PAGERDUTY', status: 'ACTIVE', credentials: '{}', config: { api_key: 'ak', service_id: 'sid', routing_key: 'rk-test' } },
    ]);

    await routeNotification({ organizationId: 'org1', severity: 'CRITICAL', title: 'Critical Alert', message: 'Something critical' });
    expect(mockPdCreateIncident).toHaveBeenCalled();
  });

  it('should dispatch recovery when notifyOnRecovery is true', async () => {
    mockFindUnique.mockResolvedValue({
      enabled: true, notifyOnRecovery: true,
      destinations: [{ integrationId: 'int1', channel: '#alerts' }],
    });
    mockFindMany.mockResolvedValue([
      { id: 'int1', type: 'SLACK', status: 'ACTIVE', accessToken: 'xoxb-test', credentials: '{}', config: {} },
    ]);

    await routeNotification({ organizationId: 'org1', severity: 'INFO', title: 'Recovered', message: 'All clear', isRecovery: true });
    expect(mockSlackSendMessage).toHaveBeenCalled();
  });

  it('should do nothing when route is disabled', async () => {
    mockFindUnique.mockResolvedValue({ enabled: false, destinations: [{ integrationId: 'int1' }] });
    await routeNotification({ organizationId: 'org1', severity: 'ERROR', title: 'Test', message: 'Test' });
    expect(mockFindMany).not.toHaveBeenCalled();
  });

  it('should do nothing when no route exists', async () => {
    mockFindUnique.mockResolvedValue(null);
    await routeNotification({ organizationId: 'org1', severity: 'INFO', title: 'Test', message: 'Test' });
    expect(mockFindMany).not.toHaveBeenCalled();
  });

  it('should skip recovery notifications when notifyOnRecovery is false', async () => {
    mockFindUnique.mockResolvedValue({
      enabled: true, notifyOnRecovery: false,
      destinations: [{ integrationId: 'int1' }],
    });
    await routeNotification({ organizationId: 'org1', severity: 'INFO', title: 'Recovered', message: 'All clear', isRecovery: true });
    expect(mockFindMany).not.toHaveBeenCalled();
  });

  it('should gracefully handle missing integration', async () => {
    mockFindUnique.mockResolvedValue({
      enabled: true, notifyOnRecovery: false,
      destinations: [{ integrationId: 'deleted-int' }],
    });
    mockFindMany.mockResolvedValue([]);
    // Should not throw
    await routeNotification({ organizationId: 'org1', severity: 'CRITICAL', title: 'Test', message: 'Test' });
  });
});
