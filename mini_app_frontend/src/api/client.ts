import type {
  GroupSettings,
  GroupStats,
  PendingReview,
  ReviewAction,
  ApiResponse,
  GroupInfo,
} from '../types';

const API_BASE = import.meta.env.VITE_API_URL || '';

class ApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = 'ApiError';
  }
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const webApp = window.Telegram?.WebApp;
  const initData = webApp?.initData || '';

  const response = await fetch(`${API_BASE}/api${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': initData,
      ...options.headers,
    },
  });

  const data: ApiResponse<T> = await response.json();

  if (!data.success || !response.ok) {
    const error = data.error || { code: 'UNKNOWN', message: 'Unknown error occurred' };
    throw new ApiError(error.code, error.message);
  }

  return data.data as T;
}

// Group endpoints
export async function getGroupInfo(groupId: number): Promise<GroupInfo> {
  return apiRequest<GroupInfo>(`/groups/${groupId}`);
}

export async function getGroupSettings(groupId: number): Promise<GroupSettings> {
  return apiRequest<GroupSettings>(`/groups/${groupId}/settings`);
}

export async function updateGroupSettings(
  groupId: number,
  settings: Partial<GroupSettings>
): Promise<GroupSettings> {
  return apiRequest<GroupSettings>(`/groups/${groupId}/settings`, {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

export async function getGroupStats(
  groupId: number,
  periodDays: number = 7
): Promise<GroupStats> {
  return apiRequest<GroupStats>(
    `/groups/${groupId}/stats?period_days=${periodDays}`
  );
}

// Review endpoints
export async function getPendingReviews(groupId: number): Promise<PendingReview[]> {
  return apiRequest<PendingReview[]>(`/groups/${groupId}/reviews`);
}

export async function submitReviewAction(
  groupId: number,
  action: ReviewAction
): Promise<{ success: boolean }> {
  return apiRequest<{ success: boolean }>(`/groups/${groupId}/reviews`, {
    method: 'POST',
    body: JSON.stringify(action),
  });
}

// Channel validation
export async function validateChannel(
  channelId: string
): Promise<{ valid: boolean; channel_id: number; title: string }> {
  return apiRequest<{ valid: boolean; channel_id: number; title: string }>(
    `/channels/validate?channel=${encodeURIComponent(channelId)}`
  );
}

export { ApiError };
