import { describe, it, expect } from 'vitest';
import { server } from '../../test/setup';
import { http, HttpResponse } from 'msw';
import {
  getGroupSettings,
  updateGroupSettings,
  getGroupStats,
  getPendingReviews,
  submitReviewAction,
  ApiError,
} from '../client';

describe('API Client', () => {
  describe('getGroupSettings', () => {
    it('should fetch group settings successfully', async () => {
      const settings = await getGroupSettings(123);

      expect(settings).toMatchObject({
        group_id: 123,
        group_type: 'general',
        sandbox_enabled: false,
      });
    });

    it('should throw ApiError on 404', async () => {
      await expect(getGroupSettings(404)).rejects.toThrow(ApiError);
      await expect(getGroupSettings(404)).rejects.toMatchObject({
        code: 'NOT_FOUND',
      });
    });

    it('should throw on client error (no retry)', async () => {
      server.use(
        http.get('/api/groups/:groupId/settings', () => {
          return HttpResponse.json(
            { success: false, error: { code: 'FORBIDDEN', message: 'Access denied' } },
            { status: 403 }
          );
        })
      );

      await expect(getGroupSettings(123)).rejects.toThrow(ApiError);
      await expect(getGroupSettings(123)).rejects.toMatchObject({
        code: 'FORBIDDEN',
        status: 403,
      });
    });
  });

  describe('updateGroupSettings', () => {
    it('should update settings and return new data', async () => {
      const updated = await updateGroupSettings(123, {
        group_type: 'tech',
        sandbox_enabled: true,
      });

      expect(updated.group_type).toBe('tech');
      expect(updated.sandbox_enabled).toBe(true);
    });
  });

  describe('getGroupStats', () => {
    it('should fetch stats with default period', async () => {
      const stats = await getGroupStats(123);

      expect(stats).toMatchObject({
        group_id: 123,
        period_days: 7,
        total_messages: 1000,
      });
    });

    it('should fetch stats with custom period', async () => {
      const stats = await getGroupStats(123, 30);

      expect(stats.period_days).toBe(30);
    });
  });

  describe('getPendingReviews', () => {
    it('should fetch pending reviews', async () => {
      const reviews = await getPendingReviews(123);

      expect(reviews).toHaveLength(2);
      expect(reviews[0]).toMatchObject({
        id: 'review-1',
        username: 'spammer1',
      });
    });
  });

  describe('submitReviewAction', () => {
    it('should submit approve action', async () => {
      const result = await submitReviewAction(123, {
        review_id: 'review-1',
        action: 'approve',
      });

      expect(result.success).toBe(true);
    });

    it('should submit confirm_block action', async () => {
      const result = await submitReviewAction(123, {
        review_id: 'review-2',
        action: 'confirm_block',
      });

      expect(result.success).toBe(true);
    });
  });
});
