import React, { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Button } from '../ui/button';

const OUTCOMES = [
  'Interested',
  'Not Interested',
  'Follow-up Scheduled',
  'Call back / Reschedule',
  'Others',
];

export function TaskCompleteModal({ open, onOpenChange, task, onConfirm, saving }) {
  const [outcome, setOutcome] = useState('');
  const [reason, setReason] = useState('');
  const requiresOutcome = (task?.sla_rule || '') === 'visit_completed' || /post-visit/i.test(task?.description || '');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (requiresOutcome && !outcome) return;
    if (outcome === 'Others' && !reason.trim()) return;
    onConfirm?.(task, {
      status: 'completed',
      ...(requiresOutcome ? { task_outcome: outcome, task_outcome_reason: reason.trim() || undefined } : {}),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-md">
        <DialogHeader>
          <DialogTitle className="font-serif text-xl">Complete task</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <p className="text-sm text-[#A1A1AA]">{task?.description}</p>
          {requiresOutcome ? (
            <>
              <div>
                <label className="text-[#A1A1AA] text-xs mb-1.5 block">Outcome *</label>
                <select
                  value={outcome}
                  onChange={(e) => setOutcome(e.target.value)}
                  className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm"
                  required
                >
                  <option value="">Select outcome</option>
                  {OUTCOMES.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              </div>
              {outcome === 'Others' ? (
                <div>
                  <label className="text-[#A1A1AA] text-xs mb-1.5 block">Reason *</label>
                  <input
                    type="text"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm"
                    required
                  />
                </div>
              ) : null}
            </>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" className="border-white/10 text-white" onClick={() => onOpenChange?.(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving} className="bg-[#C5A059] text-black hover:bg-[#E5C079]">
              {saving ? 'Saving…' : 'Complete'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default TaskCompleteModal;
