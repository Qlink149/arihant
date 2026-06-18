import React, { useEffect, useMemo, useState } from 'react';
import { Briefcase, ChevronDown, Home, MapPin, Building } from 'lucide-react';
import { toast } from 'sonner';
import { leadsAPI, myDashboardAPI, usersAPI } from '../../services/api';
import { UI_LEAD_STATUSES } from '../../constants/leadStatus';
import {
  isNurturingStatus,
  NURTURE_LABELS,
  NURTURING_STATUS,
} from '../../utils/nurtureLabel';
import { TemperatureBadge } from './TemperatureBadge';
import { CrmBadge } from '../ui/CrmBadge';
import { Button } from '../ui/button';
import { useAuth } from '../../context/AuthContext';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Input } from '../ui/input';
import { getNurtureTemperatureTintClass } from '../../utils/leadTable';

const VISIT_DATE_STATUSES = ['Site Visit Scheduled', 'SV Completed – Follow Up'];

function toLocalDatetimeInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatVisitDateDisplay(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function LeadProfileHeader({ lead, leadId, onLeadUpdated, compact = false, contactSlot = null }) {
  const { user } = useAuth();
  const [savingStatus, setSavingStatus] = useState(false);
  const [showNurturePicker, setShowNurturePicker] = useState(false);
  const [pendingNurtureLabel, setPendingNurtureLabel] = useState('');
  const temp = (lead?.temperature || '').trim();
  const showTempTint = isNurturingStatus(lead?.lead_status) && (temp === 'Hot' || temp === 'Warm');
  const tint = showTempTint
    ? getNurtureTemperatureTintClass(lead?.lead_status, temp, { includeHover: false })
    : '';

  const [assignees, setAssignees] = useState([]);
  const [loadingAssignees, setLoadingAssignees] = useState(false);
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [pendingAssigneeId, setPendingAssigneeId] = useState('');
  const [transferNotes, setTransferNotes] = useState('');
  const [transferring, setTransferring] = useState(false);

  // Contacted outcome (client confirmed)
  const OUTCOMES = ['Interested', 'Not Interested', 'Follow-up Scheduled', 'Others'];
  const [savingOutcome, setSavingOutcome] = useState(false);
  const [pendingOutcome, setPendingOutcome] = useState(lead?.logged_outcome || '');
  const [pendingOutcomeReason, setPendingOutcomeReason] = useState(lead?.logged_outcome_reason || '');

  // Lost reason (client confirmed) — required when marking Closed Lost
  const [lostModalOpen, setLostModalOpen] = useState(false);
  const [pendingLostStatus, setPendingLostStatus] = useState('');
  const [pendingLostReason, setPendingLostReason] = useState(lead?.lost_reason || '');
  const [visitDateDt, setVisitDateDt] = useState(() => toLocalDatetimeInput(lead?.visit_date_dt));
  const [savingVisitDate, setSavingVisitDate] = useState(false);
  const [extraFieldsOpen, setExtraFieldsOpen] = useState(false);

  const canAssign = useMemo(() => {
    const role = (user?.role || 'rep').toLowerCase();
    if (role === 'admin' || role === 'manager') return true;
    const uid = user?.id;
    const name = user?.full_name;
    const candidates = new Set([
      lead?.assigned_user_id,
      lead?.assigned_to,
      lead?.assigned_to_name,
      lead?.presales_agent,
    ]);
    return (uid && candidates.has(uid)) || (name && candidates.has(name));
  }, [user, lead]);

  const currentAssigneeId = lead?.assigned_user_id || '';

  const openNurturePicker = () => {
    setShowNurturePicker(true);
    setPendingNurtureLabel(
      lead?.temperature && NURTURE_LABELS.includes(lead.temperature) ? lead.temperature : ''
    );
  };

  const pendingAssignee = useMemo(
    () => assignees.find((a) => a.id === pendingAssigneeId) || null,
    [assignees, pendingAssigneeId]
  );

  useEffect(() => {
    let alive = true;
    setLoadingAssignees(true);
    usersAPI
      .listAssignees()
      .then(({ data }) => {
        if (!alive) return;
        setAssignees(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (!alive) return;
        setAssignees([]);
      })
      .finally(() => {
        if (!alive) return;
        setLoadingAssignees(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    setPendingOutcome(lead?.logged_outcome || '');
    setPendingOutcomeReason(lead?.logged_outcome_reason || '');
    setPendingLostReason(lead?.lost_reason || '');
  }, [lead?.logged_outcome, lead?.logged_outcome_reason, lead?.lost_reason]);

  useEffect(() => {
    setVisitDateDt(toLocalDatetimeInput(lead?.visit_date_dt));
  }, [lead?.visit_date_dt]);

  const showVisitDateField = VISIT_DATE_STATUSES.includes(lead?.lead_status || '');

  const hasExtraFields =
    showVisitDateField ||
    String(lead?.lead_status || '').toLowerCase() === 'contacted' ||
    showNurturePicker ||
    (lead?.visit_date_dt && !showVisitDateField);

  useEffect(() => {
    if (hasExtraFields) setExtraFieldsOpen(true);
  }, [hasExtraFields, showVisitDateField, lead?.lead_status, showNurturePicker, lead?.visit_date_dt]);

  const handleLeadStatusChange = async (newStatus) => {
    if (!newStatus) return;
    if (String(newStatus).toLowerCase() === 'closed lost') {
      setPendingLostStatus(newStatus);
      setLostModalOpen(true);
      return;
    }
    if (isNurturingStatus(newStatus)) {
      if (newStatus === lead?.lead_status && !showNurturePicker) {
        openNurturePicker();
        return;
      }
      if (newStatus === lead?.lead_status) return;
      openNurturePicker();
      return;
    }
    setShowNurturePicker(false);
    setPendingNurtureLabel('');
    setSavingStatus(true);
    try {
      const patch = { lead_status: newStatus, temperature: null };
      if (VISIT_DATE_STATUSES.includes(newStatus) && visitDateDt) {
        patch.visit_date_dt = new Date(visitDateDt).toISOString();
      }
      await leadsAPI.update(leadId, patch);
      toast.success('Lead status updated');
      await onLeadUpdated?.();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to update lead status');
    } finally {
      setSavingStatus(false);
    }
  };

  const confirmClosedLost = async () => {
    const reason = (pendingLostReason || '').trim();
    if (!reason) {
      toast.error('Lost reason is required for Closed Lost');
      return;
    }
    setSavingStatus(true);
    try {
      await leadsAPI.update(leadId, { lead_status: pendingLostStatus, temperature: null, lost_reason: reason });
      toast.success('Lead status updated');
      setLostModalOpen(false);
      setPendingLostStatus('');
      await onLeadUpdated?.();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to update lead status');
    } finally {
      setSavingStatus(false);
    }
  };

  const saveOutcome = async () => {
    const outcome = (pendingOutcome || '').trim();
    if (!OUTCOMES.includes(outcome)) {
      toast.error('Select a valid outcome');
      return;
    }
    if (outcome === 'Others' && !(pendingOutcomeReason || '').trim()) {
      toast.error('Reason is required when outcome is Others');
      return;
    }
    setSavingOutcome(true);
    try {
      await leadsAPI.update(leadId, {
        logged_outcome: outcome,
        logged_outcome_reason: outcome === 'Others' ? (pendingOutcomeReason || '').trim() : null,
      });
      toast.success('Outcome saved');
      await onLeadUpdated?.();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to save outcome');
    } finally {
      setSavingOutcome(false);
    }
  };

  const handleConfirmNurtureLabel = async () => {
    if (!pendingNurtureLabel) {
      toast.error('Select a nurture label (Hot or Warm)');
      return;
    }
    setSavingStatus(true);
    try {
      await leadsAPI.update(leadId, {
        lead_status: NURTURING_STATUS,
        temperature: pendingNurtureLabel,
      });
      toast.success('Lead status updated');
      setShowNurturePicker(false);
      setPendingNurtureLabel('');
      await onLeadUpdated?.();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to update lead status');
    } finally {
      setSavingStatus(false);
    }
  };

  const handleCancelNurture = () => {
    setShowNurturePicker(false);
    setPendingNurtureLabel('');
  };

  const saveVisitDate = async () => {
    setSavingVisitDate(true);
    try {
      await leadsAPI.update(leadId, {
        visit_date_dt: visitDateDt ? new Date(visitDateDt).toISOString() : null,
      });
      toast.success('Visit date saved');
      await onLeadUpdated?.();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to save visit date');
    } finally {
      setSavingVisitDate(false);
    }
  };

  const statusSelectValue = showNurturePicker
    ? NURTURING_STATUS
    : (lead.lead_status || '');

  const openAssignModal = (nextId) => {
    setPendingAssigneeId(nextId);
    setTransferNotes('');
    setAssignModalOpen(true);
  };

  const handleConfirmAssign = async () => {
    if (!pendingAssignee) return;
    setTransferring(true);
    try {
      await myDashboardAPI.transferLead({
        lead_id: leadId,
        to_rep: pendingAssignee.full_name,
        to_user_id: pendingAssignee.id,
        notes: transferNotes?.trim() || null,
        expected_from_user_id: lead?.assigned_user_id || null,
      });
      toast.success(`Assigned to ${pendingAssignee.full_name}`);
      setAssignModalOpen(false);
      setPendingAssigneeId('');
      setTransferNotes('');
      await onLeadUpdated?.();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Transfer failed');
    } finally {
      setTransferring(false);
    }
  };

  const selectClass = compact
    ? 'h-8 min-w-[130px] px-2 bg-black/50 border border-white/10 rounded-md text-white text-xs disabled:opacity-50'
    : 'h-9 min-w-[200px] px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm disabled:opacity-50';
  const assignSelectClass = compact
    ? 'h-8 min-w-[150px] px-2 bg-black/50 border border-white/10 rounded-md text-white text-xs disabled:opacity-50'
    : 'h-9 min-w-[240px] px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm disabled:opacity-50';
  const labelClass = 'text-[#52525B] text-[10px] uppercase tracking-wider shrink-0';
  const rowGap = compact ? 'gap-2 mt-2' : 'gap-3 mt-4';
  const inlineRow = compact ? 'flex flex-wrap items-center gap-2 mt-2' : 'mt-4 flex flex-wrap items-center gap-3';

  return (
    <div className={`flex-1 min-w-0 rounded-xl ${tint}`}>
      <div className={`flex flex-wrap items-center ${compact ? 'gap-2' : 'gap-3'}`}>
        <h1 className={compact ? 'text-lg font-semibold text-white' : 'font-serif text-3xl text-white'}>
          {lead.first_name} {lead.last_name}
        </h1>
        {compact && lead.project && (
          <span className="text-[#52525B] text-xs flex items-center gap-1">
            <Building size={12} className="text-[#C5A059]" />
            {lead.project}
          </span>
        )}
        {contactSlot}
        {lead.sla_paused && (
          <CrmBadge
            variant="warning"
            size={compact ? 'xs' : 'sm'}
            title="SLA timers start after the next status change"
          >
            {lead.import_provenance === 'freshworks' ? 'Freshworks import' : 'Imported'} — SLA paused
          </CrmBadge>
        )}
        {isNurturingStatus(lead.lead_status) && lead.temperature && (
          <TemperatureBadge
            temperature={lead.temperature}
            text={compact ? lead.temperature : `Nurturing ${lead.temperature}`}
            className={compact ? 'text-[10px] px-1.5 py-0' : 'text-sm px-3 py-1'}
          />
        )}
        {isNurturingStatus(lead.lead_status) && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={openNurturePicker}
            disabled={savingStatus}
            className="h-7 px-2 text-[#A1A1AA] hover:text-white hover:bg-white/5 text-xs"
            data-testid="change-nurture-label"
          >
            {lead.temperature ? 'Change label' : 'Set label'}
          </Button>
        )}
        {lead.vip && (
          <span className={`rounded-full font-medium bg-purple-500/20 text-purple-400 ${compact ? 'text-[10px] px-1.5 py-0' : 'px-3 py-1 text-sm'}`}>
            VIP
          </span>
        )}
      </div>

      <div className={inlineRow}>
        <label className={labelClass}>Status</label>
        <select
          value={statusSelectValue}
          onChange={(e) => handleLeadStatusChange(e.target.value)}
          disabled={savingStatus}
          className={selectClass}
          data-testid="lead-status-select"
        >
          <option value="">Select status</option>
          {UI_LEAD_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <span className="text-[#52525B] hidden sm:inline">|</span>

        <label className={labelClass}>Assign</label>
        <select
          value={currentAssigneeId}
          onChange={(e) => {
            const next = e.target.value;
            if (!next || next === currentAssigneeId) return;
            openAssignModal(next);
          }}
          disabled={!canAssign || loadingAssignees || transferring}
          className={assignSelectClass}
          data-testid="assign-to-select"
        >
          <option value="">
            {loadingAssignees ? 'Loading…' : 'Unassigned'}
          </option>
          {assignees.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name}
            </option>
          ))}
        </select>
        {!canAssign && (
          <span className="text-[#52525B] text-[10px]" data-testid="assign-to-disabled-hint">
            Owner/admin only
          </span>
        )}

        {showNurturePicker && (
          <>
            <span className="text-[#52525B] text-xs">Nurture</span>
            {NURTURE_LABELS.map((label) => (
              <label
                key={label}
                className="flex items-center gap-1 cursor-pointer text-white text-xs"
              >
                <input
                  type="radio"
                  name="nurture-label"
                  value={label}
                  checked={pendingNurtureLabel === label}
                  onChange={() => setPendingNurtureLabel(label)}
                  className="accent-[#C5A059]"
                />
                {label}
              </label>
            ))}
            <Button
              type="button"
              size="sm"
              onClick={handleConfirmNurtureLabel}
              disabled={savingStatus || !pendingNurtureLabel}
              className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90 h-7 text-xs"
            >
              Apply
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={handleCancelNurture}
              disabled={savingStatus}
              className="border-white/10 text-white h-7 text-xs"
            >
              Cancel
            </Button>
          </>
        )}

        {savingStatus && <span className="text-[#52525B] text-xs">Saving...</span>}
      </div>

      {compact && hasExtraFields && !extraFieldsOpen && (
        <button
          type="button"
          onClick={() => setExtraFieldsOpen(true)}
          className="flex items-center gap-1 mt-1.5 text-[#52525B] text-xs hover:text-[#A1A1AA]"
          data-testid="expand-extra-fields"
        >
          <ChevronDown size={12} />
          More fields
        </button>
      )}

      {(!compact || extraFieldsOpen) && showVisitDateField && (
        <div className={`flex flex-wrap items-center ${rowGap}`}>
          <label className={labelClass}>Visit Date</label>
          <input
            type="datetime-local"
            value={visitDateDt}
            onChange={(e) => setVisitDateDt(e.target.value)}
            className={compact ? 'h-8 px-2 bg-black/50 border border-white/10 rounded-md text-white text-xs' : 'h-9 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm'}
            data-testid="visit-date-dt-input"
          />
          {!visitDateDt && (
            <span className="text-amber-400/90 text-[10px]">
              Required for SLA reminders
            </span>
          )}
          <Button
            type="button"
            size="sm"
            onClick={saveVisitDate}
            disabled={savingVisitDate || !visitDateDt}
            className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90 h-7 text-xs"
            data-testid="save-visit-date"
          >
            {savingVisitDate ? 'Saving…' : 'Save'}
          </Button>
        </div>
      )}

      {(!compact || extraFieldsOpen) && lead?.visit_date_dt && !showVisitDateField && (
        <p className="mt-1.5 text-[#A1A1AA] text-xs" data-testid="visit-date-display">
          Visit: {formatVisitDateDisplay(lead.visit_date_dt)}
        </p>
      )}

      {(!compact || extraFieldsOpen) && String(lead?.lead_status || '').toLowerCase() === 'contacted' && (
        <div className={`flex flex-wrap items-center ${rowGap}`}>
          <label className={labelClass}>Outcome</label>
          <select
            value={pendingOutcome}
            onChange={(e) => setPendingOutcome(e.target.value)}
            disabled={savingOutcome}
            className={compact ? 'h-8 min-w-[150px] px-2 bg-black/50 border border-white/10 rounded-md text-white text-xs disabled:opacity-50' : 'h-9 min-w-[220px] px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm disabled:opacity-50'}
            data-testid="contacted-outcome-select"
          >
            <option value="">Select outcome</option>
            {OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
          {pendingOutcome === 'Others' && (
            <Input
              value={pendingOutcomeReason}
              onChange={(e) => setPendingOutcomeReason(e.target.value)}
              placeholder="Reason (required)"
              className="bg-black/50 border-white/10 text-white min-w-[180px] h-8 text-xs"
              data-testid="contacted-outcome-reason"
            />
          )}
          <Button
            type="button"
            size="sm"
            onClick={saveOutcome}
            disabled={savingOutcome || !pendingOutcome || (pendingOutcome === 'Others' && !(pendingOutcomeReason || '').trim())}
            className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90 h-7 text-xs"
            data-testid="save-contacted-outcome"
          >
            {savingOutcome ? 'Saving…' : 'Save'}
          </Button>
        </div>
      )}

      {!compact && (
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">
        <div className="flex items-center gap-2 text-[#A1A1AA]">
          <Briefcase size={16} className="text-[#C5A059]" />
          <span>{lead.designation || 'Not specified'}</span>
        </div>
        <div className="flex items-center gap-2 text-[#A1A1AA]">
          <MapPin size={16} className="text-[#C5A059]" />
          <span>{lead.location || 'Not specified'}</span>
        </div>
        <div className="flex items-center gap-2 text-[#A1A1AA]">
          <Home size={16} className="text-[#C5A059]" />
          <span>{lead.current_residence_type || 'Not specified'}</span>
        </div>
      </div>
      )}

      <Dialog open={assignModalOpen} onOpenChange={setAssignModalOpen}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="font-serif text-lg">Transfer lead</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-[#A1A1AA]">
              Assign <span className="text-white">{lead.first_name} {lead.last_name}</span> to{' '}
              <span className="text-white">{pendingAssignee?.full_name || '—'}</span>.
            </div>
            <div>
              <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-1">
                Note (optional)
              </label>
              <Input
                value={transferNotes}
                onChange={(e) => setTransferNotes(e.target.value)}
                placeholder="Reason / handover notes"
                className="bg-black/50 border-white/10 text-white"
                data-testid="transfer-notes-input"
              />
            </div>
            <div className="flex gap-2 justify-end pt-2">
              <Button
                type="button"
                variant="outline"
                className="border-white/10 text-white"
                onClick={() => setAssignModalOpen(false)}
                disabled={transferring}
              >
                Cancel
              </Button>
              <Button
                type="button"
                className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90"
                onClick={handleConfirmAssign}
                disabled={transferring || !pendingAssignee}
                data-testid="confirm-transfer-btn"
              >
                {transferring ? 'Transferring…' : 'Confirm'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={lostModalOpen} onOpenChange={setLostModalOpen}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="font-serif text-lg">Mark as Closed Lost</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-[#A1A1AA]">
              Provide a lost reason to mark this lead as <span className="text-white">Closed Lost</span>.
            </div>
            <div>
              <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-1">
                Lost reason (required)
              </label>
              <Input
                value={pendingLostReason}
                onChange={(e) => setPendingLostReason(e.target.value)}
                placeholder="Reason"
                className="bg-black/50 border-white/10 text-white"
                data-testid="lost-reason-input"
              />
            </div>
            <div className="flex gap-2 justify-end pt-2">
              <Button
                type="button"
                variant="outline"
                className="border-white/10 text-white"
                onClick={() => {
                  setLostModalOpen(false);
                  setPendingLostStatus('');
                }}
                disabled={savingStatus}
              >
                Cancel
              </Button>
              <Button
                type="button"
                className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90"
                onClick={confirmClosedLost}
                disabled={savingStatus || !(pendingLostReason || '').trim()}
                data-testid="confirm-closed-lost"
              >
                {savingStatus ? 'Saving…' : 'Confirm'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default LeadProfileHeader;
