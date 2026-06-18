/** Return true when metric tile arrays differ in count values. */
export function metricsCountsChanged(prev, next) {
  if (!Array.isArray(prev) || !Array.isArray(next)) return prev !== next;
  if (prev.length !== next.length) return true;
  return prev.some((m, i) => m?.count !== next[i]?.count || m?.key !== next[i]?.key);
}

/** Shallow compare two plain objects by keys. */
export function shallowEqualObjects(a, b, keys) {
  if (a === b) return true;
  if (!a || !b) return false;
  for (const key of keys) {
    if (a[key] !== b[key]) return false;
  }
  return true;
}

/** Return true when dashboard header metrics changed. */
export function dashboardMetricsChanged(prev, next) {
  if (!prev || !next) return prev !== next;
  const pm = prev.metrics || {};
  const nm = next.metrics || {};
  const keys = [
    'total_leads', 'hot', 'warm', 'site_visits', 'closed', 'conversion_rate',
    'pending_tasks', 'overdue_tasks', 'completed_tasks', 'leads_received', 'leads_transferred',
  ];
  if (keys.some((k) => pm[k] !== nm[k])) return true;
  const prevTasks = prev.my_tasks || [];
  const nextTasks = next.my_tasks || [];
  if (prevTasks.length !== nextTasks.length) return true;
  for (let i = 0; i < prevTasks.length; i += 1) {
    const a = prevTasks[i];
    const b = nextTasks[i];
    if (a?.id !== b?.id || a?.status !== b?.status || a?.due_date !== b?.due_date) return true;
  }
  return false;
}
