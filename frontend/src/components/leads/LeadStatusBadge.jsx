import React from 'react';
import { getStatusBadgeClass } from '../../utils/leadTable';
import { formatStatusDisplay, isNurturingStatus } from '../../utils/nurtureLabel';
import { TemperatureBadge } from './TemperatureBadge';

export function LeadStatusBadge({ status, temperature, className = '' }) {
  const t = (temperature || '').trim();
  const isNurtureTemp = isNurturingStatus(status) && (t === 'Hot' || t === 'Warm');

  if (isNurtureTemp) {
    return (
      <span className={`inline-flex items-center gap-1.5 ${className}`}>
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs whitespace-nowrap ${getStatusBadgeClass(
            status
          )}`}
          data-testid="status-badge-nurturing"
        >
          Nurturing
        </span>
        <TemperatureBadge temperature={t} />
      </span>
    );
  }

  const display = formatStatusDisplay(status, temperature);
  const isNew = (status || '') === 'New' || /^new$/i.test(status || '');
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs whitespace-nowrap ${getStatusBadgeClass(status)} ${isNew ? 'animate-pulse' : ''} ${className}`}
      data-testid={`status-badge-${String(display).replace(/\s+/g, '-').toLowerCase()}`}
    >
      {display}
    </span>
  );
}

export default LeadStatusBadge;
