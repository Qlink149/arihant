import React from 'react';
import { avatarHue, getLeadInitials } from '../../utils/leadTable';

export function LeadAvatar({ lead, size = 'md', className = '' }) {
  const initials = getLeadInitials(lead);
  const seed = lead?.id || `${lead?.first_name}${lead?.last_name}`;
  const hue = avatarHue(seed);
  const sizeClass =
    size === 'sm' ? 'w-7 h-7 text-xs' : size === 'lg' ? 'w-12 h-12 text-lg' : 'w-9 h-9 text-sm';

  return (
    <div
      className={`rounded-full flex items-center justify-center font-medium flex-shrink-0 ${sizeClass} ${className}`}
      style={{
        backgroundColor: `hsl(${hue} 45% 28%)`,
        color: `hsl(${hue} 70% 85%)`,
      }}
      aria-hidden
    >
      {initials}
    </div>
  );
}

export default LeadAvatar;
