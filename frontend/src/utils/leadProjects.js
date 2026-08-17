export function getLeadProjects(lead) {
  if (!lead) return [];
  if (Array.isArray(lead.projects) && lead.projects.length) {
    return lead.projects.map((p) => String(p).trim()).filter(Boolean);
  }
  if (lead.project) {
    return String(lead.project)
      .split(';')
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

export function formatLeadProjects(lead, empty = '—') {
  const names = getLeadProjects(lead);
  return names.length ? names.join('; ') : empty;
}

export function primaryLeadProject(lead, fallback = '') {
  const names = getLeadProjects(lead);
  return names[0] || fallback;
}
