import React, { memo, useCallback } from 'react';
import { LeadOverviewCard } from './LeadOverviewCard';
import { resolveDrillDown } from '../../utils/leadOverview';
import { Button } from '../ui/button';

const SKELETON_COUNT = 14;

const GRID_CLASS =
  'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3';

function MetricSkeleton() {
  return (
    <div
      className="min-h-[120px] bg-crm-elevated border border-crm-border rounded-md p-4 animate-pulse"
      aria-hidden
    >
      <div className="h-6 w-10 bg-white/10 rounded-sm mb-3" />
      <div className="h-3 w-20 bg-white/10 rounded mb-2" />
      <div className="h-8 w-12 bg-white/10 rounded mb-4" />
      <div className="h-3 w-24 bg-white/10 rounded" />
    </div>
  );
}

export const LeadOverviewGrid = memo(function LeadOverviewGrid({
  onDrillDown,
  metrics = [],
  loading = false,
  error = null,
  onRetry,
}) {
  const handleCardClick = useCallback(
    (metric) => {
      if (metric?.drill_down) {
        if (onDrillDown) {
          onDrillDown(metric.drill_down, metric);
        } else {
          resolveDrillDown(metric.drill_down, {});
        }
      }
    },
    [onDrillDown],
  );

  if (loading) {
    return (
      <div className={GRID_CLASS} data-testid="lead-overview-loading">
        {Array.from({ length: SKELETON_COUNT }, (_, i) => (
          <MetricSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-crm-border bg-crm-elevated p-6 text-center"
        data-testid="lead-overview-error"
      >
        <p className="text-sm text-crm-fg-secondary mb-3">{error}</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="border-crm-border text-crm-fg"
          onClick={onRetry}
        >
          Retry
        </Button>
      </div>
    );
  }

  return (
    <section aria-label="Lead overview" data-testid="lead-overview-grid">
      <h2 className="sr-only">Lead Overview</h2>
      <div className={GRID_CLASS}>
        {metrics.map((metric) => (
          <LeadOverviewCard
            key={metric.key}
            metric={metric}
            onClick={handleCardClick}
          />
        ))}
      </div>
    </section>
  );
});

export default LeadOverviewGrid;
