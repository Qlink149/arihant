import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Download, Loader2, CheckSquare, Square } from 'lucide-react';
import { toast } from 'sonner';
import { leadsAPI } from '../../services/api';
import { Button } from '../ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';

const POLL_MS = 1500;

function triggerBlobDownload(blob, filename) {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename || 'leads-export.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export function LeadExportModal({
  open,
  onOpenChange,
  totalLeads,
  activeFiltersCount,
  exportParams,
}) {
  const [fieldsCatalog, setFieldsCatalog] = useState([]);
  const [selectedFields, setSelectedFields] = useState(new Set());
  const [loadingFields, setLoadingFields] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [job, setJob] = useState(null);
  const pollRef = useRef(null);

  const groupedFields = useMemo(() => {
    const groups = {};
    fieldsCatalog.forEach((f) => {
      const g = f.group || 'Other';
      if (!groups[g]) groups[g] = [];
      groups[g].push(f);
    });
    return groups;
  }, [fieldsCatalog]);

  const resetState = useCallback(() => {
    setExporting(false);
    setJob(null);
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!open) {
      resetState();
      return undefined;
    }
    let alive = true;
    setLoadingFields(true);
    leadsAPI
      .getExportFields()
      .then(({ data }) => {
        if (!alive) return;
        const fields = Array.isArray(data?.fields) ? data.fields : [];
        setFieldsCatalog(fields);
        setSelectedFields(new Set(fields.filter((f) => f.default).map((f) => f.key)));
      })
      .catch((err) => {
        if (!alive) return;
        toast.error(err.response?.data?.detail || 'Failed to load export fields');
      })
      .finally(() => {
        if (alive) setLoadingFields(false);
      });
    return () => { alive = false; };
  }, [open]);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  const toggleField = (key) => {
    setSelectedFields((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const selectAll = () => setSelectedFields(new Set(fieldsCatalog.map((f) => f.key)));
  const clearAll = () => setSelectedFields(new Set());

  const pollJob = useCallback((jobId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await leadsAPI.getExportJob(jobId);
        setJob(data);
        if (data.status === 'completed') {
          clearInterval(pollRef.current);
          pollRef.current = null;
          const blobRes = await leadsAPI.downloadExport(jobId);
          triggerBlobDownload(blobRes.data, data.filename);
          toast.success(`Exported ${data.processed_count?.toLocaleString()} leads`);
          setExporting(false);
        } else if (data.status === 'failed') {
          clearInterval(pollRef.current);
          pollRef.current = null;
          toast.error(data.error || 'Export failed');
          setExporting(false);
        }
      } catch (err) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        toast.error(err.response?.data?.detail || 'Export status check failed');
        setExporting(false);
      }
    }, POLL_MS);
  }, []);

  const handleStartExport = async () => {
    if (selectedFields.size === 0) {
      toast.error('Select at least one field to export');
      return;
    }
    if (!totalLeads) {
      toast.error('No leads to export');
      return;
    }
    setExporting(true);
    try {
      const { data } = await leadsAPI.startExport(
        exportParams,
        Array.from(selectedFields),
      );
      setJob(data);
      pollJob(data.id);
    } catch (err) {
      setExporting(false);
      toast.error(err.response?.data?.detail || 'Failed to start export');
    }
  };

  const progressPct = job?.total_count
    ? Math.min(100, Math.round((job.processed_count / job.total_count) * 100))
    : 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="crm-export-modal border-border bg-background text-foreground max-w-lg max-h-[85vh] overflow-hidden flex flex-col"
        data-testid="lead-export-modal"
      >
        <DialogHeader>
          <DialogTitle className="font-serif text-xl flex items-center gap-2 text-foreground">
            <Download className="text-[#C5A059]" size={20} />
            Export Leads to CSV
          </DialogTitle>
        </DialogHeader>

        <div className="crm-export-summary rounded-lg border px-4 py-3 text-sm">
          <p className="text-foreground font-medium">
            Export {totalLeads.toLocaleString()} lead{totalLeads === 1 ? '' : 's'}
          </p>
          {activeFiltersCount > 0 && (
            <p className="text-muted-foreground text-xs mt-1">Matching your current filters</p>
          )}
        </div>

        {exporting ? (
          <div className="py-8 space-y-4" data-testid="export-progress">
            <div className="flex items-center justify-center gap-2 text-muted-foreground">
              <Loader2 className="animate-spin text-[#C5A059]" size={20} />
              <span>
                Processing {job?.processed_count?.toLocaleString() ?? 0} of{' '}
                {job?.total_count?.toLocaleString() ?? totalLeads.toLocaleString()} leads…
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full bg-[#C5A059] transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <p className="text-center text-muted-foreground text-xs">
              Your download will start automatically when ready.
            </p>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2">
              <p className="text-muted-foreground text-sm">Select columns to export</p>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground hover:text-foreground h-7 text-xs"
                  onClick={selectAll}
                >
                  Select all
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground hover:text-foreground h-7 text-xs"
                  onClick={clearAll}
                >
                  Clear all
                </Button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto space-y-4 pr-1 min-h-[200px] max-h-[340px]">
              {loadingFields ? (
                <p className="text-muted-foreground text-sm py-4">Loading fields…</p>
              ) : (
                Object.entries(groupedFields).map(([group, items]) => (
                  <div key={group}>
                    <p className="text-muted-foreground text-xs uppercase tracking-wider mb-2">{group}</p>
                    <div className="space-y-1">
                      {items.map((field) => {
                        const checked = selectedFields.has(field.key);
                        return (
                          <button
                            key={field.key}
                            type="button"
                            onClick={() => toggleField(field.key)}
                            className="crm-export-field w-full flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-muted/80 text-left text-sm text-foreground"
                            data-testid={`export-field-${field.key}`}
                          >
                            {checked ? (
                              <CheckSquare size={16} className="text-[#C5A059] shrink-0" />
                            ) : (
                              <Square size={16} className="text-muted-foreground shrink-0" />
                            )}
                            <span className="text-foreground">{field.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="flex gap-3 pt-2">
              <Button
                variant="outline"
                onClick={() => onOpenChange(false)}
                className="flex-1 border-border text-foreground hover:bg-muted"
              >
                Cancel
              </Button>
              <Button
                onClick={handleStartExport}
                disabled={loadingFields || selectedFields.size === 0 || !totalLeads}
                className="flex-1 bg-[#C5A059] text-black hover:bg-[#E5C079] disabled:opacity-50"
                data-testid="start-export-btn"
              >
                Start Export
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
