import React from 'react';
import { getStatusBadgeVariant } from '../../constants/badgeVariants';
import { formatStatusDisplay, isNurturingStatus } from '../../utils/nurtureLabel';
import { CrmBadge } from '../ui/CrmBadge';
import { TemperatureBadge } from './TemperatureBadge';

export function LeadStatusBadge({ status, temperature, className = '' }) {
  const t = (temperature || '').trim();
  const isNurtureTemp = isNurturingStatus(status) && (t === 'Hot' || t === 'Warm');
  const variant = getStatusBadgeVariant(status);
  const isNew = variant === 'new';

  if (isNurtureTemp) {
    return (
      <span className={`inline-flex flex-wrap items-center gap-1 max-w-full ${className}`}>
        <CrmBadge variant="orange" data-testid="status-badge-nurturing">
          Nurturing
        </CrmBadge>
        <TemperatureBadge temperature={t} />
      </span>
    );
  }

  const display = formatStatusDisplay(status, temperature);

  return (
    <CrmBadge
      variant={variant}
      pulse={isNew}
      className={className}
      data-testid={`status-badge-${String(display).replace(/\s+/g, '-').toLowerCase()}`}
    >
      {display}
    </CrmBadge>
  );
}

export default LeadStatusBadge;
