import React from 'react';
import { cn } from '@/lib/utils';

/**
 * Theme-aware badge/chip using CSS variables (.crm-badge / .crm-chip in index.css).
 * @param {'gold'|'danger'|'warning'|'success'|'info'|'neutral'|'purple'|'teal'|'cyan'|'sky'|'orange'|'emerald'|'amber'|'new'} variant
 */
export function CrmBadge({
  variant = 'neutral',
  size = 'sm',
  pulse = false,
  chip = false,
  uppercase = false,
  className,
  children,
  ...props
}) {
  const baseClass = chip ? 'crm-chip' : 'crm-badge';
  const variantClass = chip ? `crm-chip--${variant}` : `crm-badge--${variant}`;

  return (
    <span
      className={cn(
        baseClass,
        variantClass,
        !chip && size === 'xs' && 'crm-badge--xs',
        !chip && uppercase && 'crm-badge--uppercase',
        !chip && pulse && 'crm-badge--pulse',
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}

export default CrmBadge;
