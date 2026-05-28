import React from 'react';
import { Flame, ThermometerSun } from 'lucide-react';

const normalizeTemp = (t) => (t || '').trim().toLowerCase();

export function TemperatureBadge({ temperature, text, className = '' }) {
  const t = normalizeTemp(temperature);
  if (t !== 'hot' && t !== 'warm') return null;

  const isHot = t === 'hot';
  const Icon = isHot ? Flame : ThermometerSun;
  const label = text || (isHot ? 'Hot' : 'Warm');

  return (
    <span
      className={`temp-badge ${isHot ? 'temp-badge--hot' : 'temp-badge--warm'} ${className}`}
      data-testid={`temperature-badge-${t}`}
    >
      <Icon size={12} className="temp-badge__icon" aria-hidden />
      <span className="temp-badge__text">{label}</span>
    </span>
  );
}

export default TemperatureBadge;

