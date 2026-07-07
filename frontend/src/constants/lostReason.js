/** Canonical lost-reason picklist (mirrors backend LOST_REASON_OPTIONS). */

export const LOST_REASON_OPTIONS = [
  'Not able to reach',
  'Ringing no response',
  'Not interested',
  'Lost to competitor',
  'Budget',
  'Location',
  'Other Enquiry',
  'Channel Partner',
  'Possession Date mismatch',
  'Unit size',
  'Rental',
];

export const isLostReasonStatus = (status) => {
  const s = (status || '').trim().toLowerCase();
  return s === 'unqualified' || s === 'closed lost';
};

/** Statuses that use the enum dropdown (vs free-text) in the lost modal. */
export const isLostReasonEnumStatus = (status) => isLostReasonStatus(status);

export const isCanonicalLostReason = (value) =>
  LOST_REASON_OPTIONS.includes((value || '').trim());
