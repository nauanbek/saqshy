import React, { useState, useEffect, useCallback } from 'react';
import type { GroupSettings, GroupType } from '../types';
import { GroupTypeSelector } from './GroupTypeSelector';
import { LoadingSpinner } from './LoadingSpinner';
import { validateChannel } from '../api/client';
import { useTelegram } from '../hooks/useTelegram';

interface SettingsFormProps {
  settings: GroupSettings;
  onSave: (settings: Partial<GroupSettings>) => Promise<void>;
  isSaving: boolean;
}

export function SettingsForm({
  settings,
  onSave,
  isSaving,
}: SettingsFormProps): React.ReactElement {
  const { hapticFeedback, showAlert } = useTelegram();

  // Local form state
  const [groupType, setGroupType] = useState<GroupType>(settings.group_type);
  const [linkedChannelInput, setLinkedChannelInput] = useState<string>(
    settings.linked_channel_id?.toString() || ''
  );
  const [linkedChannelId, setLinkedChannelId] = useState<number | null>(settings.linked_channel_id);
  const [sandboxEnabled, setSandboxEnabled] = useState(settings.sandbox_enabled);
  const [sandboxDuration, setSandboxDuration] = useState(settings.sandbox_duration_hours);
  const [adminNotifications, setAdminNotifications] = useState(settings.admin_notifications);

  // Channel validation state
  const [channelValidating, setChannelValidating] = useState(false);
  const [channelError, setChannelError] = useState<string | null>(null);
  const [channelTitle, setChannelTitle] = useState<string | null>(null);

  // Track if form has changes
  const [hasChanges, setHasChanges] = useState(false);

  // Check for changes
  useEffect(() => {
    const changed =
      groupType !== settings.group_type ||
      linkedChannelId !== settings.linked_channel_id ||
      sandboxEnabled !== settings.sandbox_enabled ||
      sandboxDuration !== settings.sandbox_duration_hours ||
      adminNotifications !== settings.admin_notifications;

    setHasChanges(changed);
  }, [groupType, linkedChannelId, sandboxEnabled, sandboxDuration, adminNotifications, settings]);

  // Validate channel
  const handleValidateChannel = useCallback(async () => {
    if (!linkedChannelInput.trim()) {
      setLinkedChannelId(null);
      setChannelTitle(null);
      setChannelError(null);
      return;
    }

    setChannelValidating(true);
    setChannelError(null);

    try {
      const result = await validateChannel(linkedChannelInput.trim());
      if (result.valid) {
        setLinkedChannelId(result.channel_id);
        setChannelTitle(result.title);
        hapticFeedback.notification('success');
      } else {
        setChannelError('Invalid channel or bot not added as admin');
        setLinkedChannelId(null);
        setChannelTitle(null);
        hapticFeedback.notification('error');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to validate channel';
      setChannelError(message);
      setLinkedChannelId(null);
      setChannelTitle(null);
      hapticFeedback.notification('error');
    } finally {
      setChannelValidating(false);
    }
  }, [linkedChannelInput, hapticFeedback]);

  // Handle unlinking channel
  const handleUnlinkChannel = () => {
    setLinkedChannelInput('');
    setLinkedChannelId(null);
    setChannelTitle(null);
    setChannelError(null);
    hapticFeedback.selection();
  };

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!hasChanges) return;

    try {
      await onSave({
        group_type: groupType,
        linked_channel_id: linkedChannelId,
        sandbox_enabled: sandboxEnabled,
        sandbox_duration_hours: sandboxDuration,
        admin_notifications: adminNotifications,
      });
      hapticFeedback.notification('success');
      await showAlert('Settings saved successfully!');
    } catch (error) {
      hapticFeedback.notification('error');
      const message = error instanceof Error ? error.message : 'Failed to save settings';
      await showAlert(`Error: ${message}`);
    }
  };

  return (
    <form className="settings-form" onSubmit={handleSubmit}>
      {/* Group Type */}
      <GroupTypeSelector value={groupType} onChange={setGroupType} disabled={isSaving} />

      {/* Channel Linking */}
      <div className="settings-section" role="group" aria-labelledby="channel-section-title">
        <h3 className="section-title" id="channel-section-title">
          Linked Channel
        </h3>
        <p className="section-hint" id="channel-section-hint">
          Users subscribed to this channel get trust bonus (-25 points)
        </p>

        {linkedChannelId && channelTitle ? (
          <div className="linked-channel-display">
            <div className="linked-channel-info">
              <span className="channel-title">{channelTitle}</span>
              <span className="channel-id">ID: {linkedChannelId}</span>
            </div>
            <button
              type="button"
              className="btn btn-secondary btn-small"
              onClick={handleUnlinkChannel}
              disabled={isSaving}
              aria-label={`Unlink channel ${channelTitle}`}
            >
              Unlink
            </button>
          </div>
        ) : (
          <div className="channel-input-group">
            <label htmlFor="channel-input" className="sr-only">
              Channel username or ID
            </label>
            <input
              id="channel-input"
              type="text"
              className="input"
              placeholder="@channel or channel ID"
              value={linkedChannelInput}
              onChange={(e) => {
                setLinkedChannelInput(e.target.value);
                setChannelError(null);
              }}
              disabled={isSaving || channelValidating}
              aria-describedby="channel-section-hint channel-error"
              aria-invalid={channelError ? 'true' : undefined}
            />
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleValidateChannel}
              disabled={isSaving || channelValidating || !linkedChannelInput.trim()}
              aria-label="Validate channel"
            >
              {channelValidating ? <LoadingSpinner size="small" /> : 'Validate'}
            </button>
          </div>
        )}

        {channelError && (
          <div className="error-message" id="channel-error" role="alert">
            {channelError}
          </div>
        )}
      </div>

      {/* Sandbox Settings */}
      <div className="settings-section" role="group" aria-labelledby="sandbox-section-title">
        <h3 className="section-title" id="sandbox-section-title">
          Sandbox Mode
        </h3>
        <p className="section-hint" id="sandbox-section-hint">
          New users are restricted for a period before gaining full access
        </p>

        <label className="toggle-row">
          <span className="toggle-label" id="sandbox-toggle-label">
            Enable Sandbox
          </span>
          <input
            type="checkbox"
            className="toggle-input"
            checked={sandboxEnabled}
            onChange={(e) => {
              hapticFeedback.selection();
              setSandboxEnabled(e.target.checked);
            }}
            disabled={isSaving}
            aria-labelledby="sandbox-toggle-label"
            aria-describedby="sandbox-section-hint"
          />
          <span className="toggle-switch" aria-hidden="true"></span>
        </label>

        {sandboxEnabled && (
          <div className="slider-group">
            <label className="slider-label" id="sandbox-duration-label" htmlFor="sandbox-duration">
              Duration: <strong>{sandboxDuration} hours</strong>
            </label>
            <input
              id="sandbox-duration"
              type="range"
              className="slider"
              min={6}
              max={48}
              step={6}
              value={sandboxDuration}
              onChange={(e) => {
                hapticFeedback.selection();
                setSandboxDuration(parseInt(e.target.value, 10));
              }}
              disabled={isSaving}
              aria-valuemin={6}
              aria-valuemax={48}
              aria-valuenow={sandboxDuration}
              aria-valuetext={`${sandboxDuration} hours`}
            />
            <div className="slider-labels" aria-hidden="true">
              <span>6h</span>
              <span>24h</span>
              <span>48h</span>
            </div>
          </div>
        )}
      </div>

      {/* Admin Notifications */}
      <div className="settings-section" role="group" aria-labelledby="notifications-section-title">
        <h3 className="section-title" id="notifications-section-title">
          Notifications
        </h3>

        <label className="toggle-row">
          <span className="toggle-label" id="admin-notifications-label">
            Admin Notifications
          </span>
          <input
            type="checkbox"
            className="toggle-input"
            checked={adminNotifications}
            onChange={(e) => {
              hapticFeedback.selection();
              setAdminNotifications(e.target.checked);
            }}
            disabled={isSaving}
            aria-labelledby="admin-notifications-label"
            aria-describedby="admin-notifications-hint"
          />
          <span className="toggle-switch" aria-hidden="true"></span>
        </label>
        <p className="toggle-hint" id="admin-notifications-hint">
          Receive notifications about blocked messages requiring review
        </p>
      </div>

      {/* Save Button */}
      <div className="form-actions">
        <button
          type="submit"
          className="btn btn-primary btn-large"
          disabled={isSaving || !hasChanges}
        >
          {isSaving ? (
            <>
              <LoadingSpinner size="small" />
              <span>Saving...</span>
            </>
          ) : (
            'Save Settings'
          )}
        </button>
        {hasChanges && !isSaving && <p className="unsaved-changes">You have unsaved changes</p>}
      </div>
    </form>
  );
}
