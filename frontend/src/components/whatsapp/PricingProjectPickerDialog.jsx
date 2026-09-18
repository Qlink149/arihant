import React, { useEffect, useMemo, useState } from 'react';
import { IndianRupee } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import { Button } from '../ui/button';
import {
  WHATSAPP_PRICING_PROJECTS,
  getPricingProjectByKey,
  resolvePricingProjectKey,
} from '../../constants/whatsappPricingProjects';
import { getLeadProjects } from '../../utils/leadProjects';

function ProjectOption({ option, leadName, selected, onSelect }) {
  const isLeadProject = Boolean(leadName);
  const disabled = !option.priced;

  return (
    <button
      type="button"
      data-testid={`pricing-option-${option.key}`}
      disabled={disabled}
      onClick={() => !disabled && onSelect(option.key)}
      className={`w-full text-left rounded-lg border px-3 py-2.5 transition-colors ${
        disabled
          ? 'border-crm-border/50 opacity-50 cursor-not-allowed'
          : selected === option.key
            ? 'border-crm-accent bg-crm-accent/10'
            : 'border-crm-border hover:border-crm-accent/50 hover:bg-white/5'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-crm-fg">
            {isLeadProject ? leadName : option.label}
            {isLeadProject && leadName !== option.label && (
              <span className="text-crm-fg-muted font-normal"> · {option.label}</span>
            )}
          </p>
          {option.priced ? (
            <p className="text-xs text-crm-fg-muted mt-0.5">{option.pricePreview}</p>
          ) : (
            <p className="text-xs text-crm-fg-muted mt-0.5">Pricing not available</p>
          )}
        </div>
        {isLeadProject && (
          <span className="text-[10px] uppercase tracking-wide text-crm-accent shrink-0">
            Lead
          </span>
        )}
      </div>
    </button>
  );
}

export function PricingProjectPickerDialog({
  open,
  onOpenChange,
  lead,
  onConfirm,
  loading = false,
}) {
  const [selected, setSelected] = useState('');

  const leadProjectEntries = useMemo(() => {
    const names = getLeadProjects(lead);
    const seen = new Set();
    const entries = [];
    for (const name of names) {
      const key = resolvePricingProjectKey(name);
      if (!key || seen.has(key)) continue;
      const option = getPricingProjectByKey(key);
      if (!option) continue;
      seen.add(key);
      entries.push({ key, leadName: name, option });
    }
    return entries;
  }, [lead]);

  const otherProjects = useMemo(() => {
    const leadKeys = new Set(leadProjectEntries.map((e) => e.key));
    return WHATSAPP_PRICING_PROJECTS.filter((p) => !leadKeys.has(p.key));
  }, [leadProjectEntries]);

  useEffect(() => {
    if (!open) {
      setSelected('');
      return;
    }
    const firstPriced = leadProjectEntries.find((e) => e.option.priced);
    setSelected(firstPriced?.key || '');
  }, [open, leadProjectEntries]);

  const handleConfirm = () => {
    if (!selected || loading) return;
    onConfirm(selected);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-crm-elevated border-crm-border text-crm-fg max-w-md"
        data-testid="pricing-project-picker"
      >
        <DialogHeader>
          <DialogTitle className="font-serif text-xl flex items-center gap-2">
            <IndianRupee size={20} className="text-crm-accent" />
            Send pricing
          </DialogTitle>
        </DialogHeader>
        <p className="text-sm text-crm-fg-muted -mt-2">
          Choose which project pricing to send to the lead.
        </p>

        <div className="space-y-4 max-h-[60vh] overflow-y-auto">
          {leadProjectEntries.length > 0 && (
            <div className="space-y-2">
              <p className="text-[11px] uppercase tracking-wide text-crm-fg-muted">
                Lead projects
              </p>
              {leadProjectEntries.map(({ key, leadName, option }) => (
                <ProjectOption
                  key={`lead-${key}`}
                  option={option}
                  leadName={leadName}
                  selected={selected}
                  onSelect={setSelected}
                />
              ))}
            </div>
          )}

          {otherProjects.length > 0 && (
            <div className="space-y-2">
              <p className="text-[11px] uppercase tracking-wide text-crm-fg-muted">
                {leadProjectEntries.length > 0 ? 'All projects' : 'Projects'}
              </p>
              {otherProjects.map((option) => (
                <ProjectOption
                  key={option.key}
                  option={option}
                  selected={selected}
                  onSelect={setSelected}
                />
              ))}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="outline"
            className="border-crm-border"
            onClick={() => onOpenChange(false)}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleConfirm}
            disabled={!selected || loading}
            data-testid="pricing-project-send"
          >
            {loading ? 'Sending…' : 'Send pricing'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
