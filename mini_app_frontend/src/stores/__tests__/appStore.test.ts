import { describe, it, expect, beforeEach } from 'vitest';
import { useAppStore } from '../appStore';

describe('appStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useAppStore.setState({
      groupId: null,
      colorScheme: 'light',
      isInitialized: false,
      initError: null,
    });
  });

  describe('groupId', () => {
    it('should set groupId', () => {
      useAppStore.getState().setGroupId(123);
      expect(useAppStore.getState().groupId).toBe(123);
    });

    it('should set groupId to null', () => {
      useAppStore.getState().setGroupId(123);
      useAppStore.getState().setGroupId(null);
      expect(useAppStore.getState().groupId).toBeNull();
    });
  });

  describe('colorScheme', () => {
    it('should set colorScheme to dark', () => {
      useAppStore.getState().setColorScheme('dark');
      expect(useAppStore.getState().colorScheme).toBe('dark');
    });

    it('should set colorScheme to light', () => {
      useAppStore.getState().setColorScheme('dark');
      useAppStore.getState().setColorScheme('light');
      expect(useAppStore.getState().colorScheme).toBe('light');
    });
  });

  describe('isInitialized', () => {
    it('should set isInitialized', () => {
      useAppStore.getState().setInitialized(true);
      expect(useAppStore.getState().isInitialized).toBe(true);
    });
  });

  describe('initError', () => {
    it('should set initError', () => {
      useAppStore.getState().setInitError('Test error');
      expect(useAppStore.getState().initError).toBe('Test error');
    });

    it('should clear initError', () => {
      useAppStore.getState().setInitError('Test error');
      useAppStore.getState().setInitError(null);
      expect(useAppStore.getState().initError).toBeNull();
    });
  });
});
