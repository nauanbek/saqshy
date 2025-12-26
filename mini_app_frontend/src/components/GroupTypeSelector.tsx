import React, { useState } from 'react';
import type { GroupType, GroupTypeOption } from '../types';
import { useTelegram } from '../hooks/useTelegram';

const GROUP_TYPES: GroupTypeOption[] = [
  {
    value: 'general',
    label: 'General',
    description: 'Balanced moderation for typical communities',
    icon: '(chat)',
  },
  {
    value: 'tech',
    label: 'Tech/Dev',
    description: 'Allows GitHub, docs, and developer links freely',
    icon: '(code)',
  },
  {
    value: 'deals',
    label: 'Deals & Promo',
    description: 'Links, promo codes, and affiliate content allowed. Soft moderation.',
    icon: '(cart)',
  },
  {
    value: 'crypto',
    label: 'Crypto',
    description: 'Strict scam detection, normal crypto discussion allowed',
    icon: '(btc)',
  },
];

interface GroupTypeSelectorProps {
  value: GroupType;
  onChange: (type: GroupType) => void;
  disabled?: boolean;
}

export function GroupTypeSelector({
  value,
  onChange,
  disabled = false,
}: GroupTypeSelectorProps): React.ReactElement {
  const { showConfirm, hapticFeedback } = useTelegram();
  const [pendingType, setPendingType] = useState<GroupType | null>(null);

  const handleSelect = async (type: GroupType) => {
    if (type === value || disabled) return;

    hapticFeedback.selection();
    setPendingType(type);

    const confirmed = await showConfirm(
      `Change group type to "${GROUP_TYPES.find((t) => t.value === type)?.label}"?\n\nThis will affect how messages are moderated.`
    );

    if (confirmed) {
      hapticFeedback.notification('success');
      onChange(type);
    }

    setPendingType(null);
  };

  return (
    <div className="group-type-selector">
      <h3 className="section-title">Group Type</h3>
      <p className="section-hint">
        Determines moderation thresholds and allowed content
      </p>

      <div className="type-options">
        {GROUP_TYPES.map((type) => (
          <button
            key={type.value}
            className={`type-option ${value === type.value ? 'selected' : ''} ${
              pendingType === type.value ? 'pending' : ''
            } ${type.value === 'deals' ? 'highlight' : ''}`}
            onClick={() => handleSelect(type.value)}
            disabled={disabled}
            aria-pressed={value === type.value}
          >
            <span className="type-option-icon">{type.icon}</span>
            <div className="type-option-content">
              <span className="type-option-label">{type.label}</span>
              <span className="type-option-description">{type.description}</span>
            </div>
            {value === type.value && (
              <span className="type-option-check" aria-hidden="true">
                [ok]
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
