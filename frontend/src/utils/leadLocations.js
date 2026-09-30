// batch3(item4): #51 Location Interested multi-select. Mirrors leadProjects.js
// so both a legacy scalar string and the new list shape read correctly.

export function getLeadLocations(lead) {
  if (!lead) return [];
  if (Array.isArray(lead.location) && lead.location.length) {
    return lead.location.map((l) => String(l).trim()).filter(Boolean);
  }
  if (lead.location) {
    return [String(lead.location).trim()].filter(Boolean);
  }
  return [];
}

export function formatLeadLocations(lead, empty = 'Not specified') {
  const names = getLeadLocations(lead);
  return names.length ? names.join('; ') : empty;
}
