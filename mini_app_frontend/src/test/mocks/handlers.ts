import { http, HttpResponse } from 'msw';

// Mock data
const mockGroupSettings = {
  group_id: 123,
  group_type: 'general' as const,
  linked_channel_id: null,
  sandbox_enabled: false,
  sandbox_duration_hours: 24,
  admin_notifications: true,
  custom_whitelist: [],
  custom_blacklist: [],
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

const mockGroupStats = {
  group_id: 123,
  period_days: 7,
  total_messages: 1000,
  allowed: 900,
  watched: 50,
  limited: 30,
  reviewed: 15,
  blocked: 5,
  fp_count: 2,
  fp_rate: 0.02,
  group_type: 'general' as const,
  top_threat_types: [
    { type: 'SPAM', count: 20 },
    { type: 'SCAM', count: 10 },
  ],
};

const mockReviews = [
  {
    id: 'review-1',
    group_id: 123,
    user_id: 111,
    username: 'spammer1',
    message_preview: 'Buy crypto now! Limited time offer...',
    risk_score: 85,
    verdict: 'review',
    threat_types: ['SCAM', 'CRYPTO_SCAM'],
    created_at: '2024-01-15T10:00:00Z',
    message_id: 1001,
  },
  {
    id: 'review-2',
    group_id: 123,
    user_id: 222,
    username: null,
    message_preview: 'Check out this amazing deal...',
    risk_score: 78,
    verdict: 'review',
    threat_types: ['SPAM'],
    created_at: '2024-01-15T09:30:00Z',
    message_id: 1002,
  },
];

// Handlers
export const handlers = [
  // Group settings
  http.get('/api/groups/:groupId/settings', ({ params }) => {
    const groupId = Number(params.groupId);
    if (groupId === 404) {
      return HttpResponse.json(
        {
          success: false,
          error: { code: 'NOT_FOUND', message: 'Group not found' },
        },
        { status: 404 }
      );
    }
    return HttpResponse.json({
      success: true,
      data: { ...mockGroupSettings, group_id: groupId },
    });
  }),

  http.put('/api/groups/:groupId/settings', async ({ params, request }) => {
    const groupId = Number(params.groupId);
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      success: true,
      data: {
        ...mockGroupSettings,
        group_id: groupId,
        ...body,
        updated_at: new Date().toISOString(),
      },
    });
  }),

  // Group stats
  http.get('/api/groups/:groupId/stats', ({ params, request }) => {
    const groupId = Number(params.groupId);
    const url = new URL(request.url);
    const periodDays = Number(url.searchParams.get('period_days')) || 7;
    return HttpResponse.json({
      success: true,
      data: { ...mockGroupStats, group_id: groupId, period_days: periodDays },
    });
  }),

  // Reviews
  http.get('/api/groups/:groupId/reviews', ({ params }) => {
    const groupId = Number(params.groupId);
    return HttpResponse.json({
      success: true,
      data: mockReviews.map((r) => ({ ...r, group_id: groupId })),
    });
  }),

  http.post('/api/groups/:groupId/reviews', async ({ request }) => {
    const body = (await request.json()) as { review_id: string; action: string };
    return HttpResponse.json({
      success: true,
      data: { success: true, review_id: body.review_id, action: body.action },
    });
  }),

  // Channel validation
  http.get('/api/channels/validate', ({ request }) => {
    const url = new URL(request.url);
    const channel = url.searchParams.get('channel');
    if (channel === 'invalid') {
      return HttpResponse.json({
        success: false,
        error: { code: 'NOT_FOUND', message: 'Channel not found' },
      });
    }
    return HttpResponse.json({
      success: true,
      data: {
        valid: true,
        channel_id: 123456,
        title: 'Test Channel',
      },
    });
  }),
];

// Export mock data for assertions
export { mockGroupSettings, mockGroupStats, mockReviews };
