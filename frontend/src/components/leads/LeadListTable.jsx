import React, { memo, useCallback } from 'react';
import { LeadDataTable } from './LeadDataTable';
import { Button } from '../ui/button';
import { TABLE_DENSITY_STORAGE_KEY } from '../../constants/performanceFlags';

export const LeadListTable = memo(function LeadListTable({
  leads,
  loading,
  loadingMore,
  pendingTaskMap,
  earliestTaskMap,
  tableDensity,
  onTableDensityChange,
  onRowClick,
  onNote,
  onOpenLeadTasks,
  loadMoreSentinelRef,
}) {
  const toggleDensity = useCallback(() => {
    onTableDensityChange((prev) => {
      const next = prev === 'compact' ? 'comfortable' : 'compact';
      try {
        localStorage.setItem(TABLE_DENSITY_STORAGE_KEY, next);
      } catch {
        /* ignore */
      }
      return next;
    });
  }, [onTableDensityChange]);

  return (
    <>
      <div className="flex justify-end">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={toggleDensity}
          className="h-8 border-white/10 text-[#A1A1AA] hover:text-white text-xs"
          data-testid="table-density-toggle"
        >
          {tableDensity === 'compact' ? 'Comfortable rows' : 'Compact rows'}
        </Button>
      </div>
      <LeadDataTable
        leads={leads}
        loading={loading}
        pendingTaskMap={pendingTaskMap}
        earliestTaskMap={earliestTaskMap}
        onRowClick={onRowClick}
        onView={onRowClick}
        onNote={onNote}
        onOpenLeadTasks={onOpenLeadTasks}
        density={tableDensity}
      />
      {!loading && leads.length > 0 && (
        <>
          <div ref={loadMoreSentinelRef} className="h-1 w-full" aria-hidden />
          {loadingMore && (
            <p className="text-center text-[#52525B] text-sm py-3 w-full">Loading more leads…</p>
          )}
        </>
      )}
    </>
  );
});
