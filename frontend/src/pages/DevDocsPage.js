import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { toast } from 'sonner';
import api from '../services/api';
import {
  Database, Server, Code, FileText, ArrowRight, ChevronDown,
  ChevronRight, Copy, Check, Globe, Lock, Layers
} from 'lucide-react';
import { Button } from '../components/ui/button';

const COLLECTIONS = [
  { name: 'leads', desc: 'Customer/lead profiles and CRM data', fields: [
    { name: 'id', type: 'UUID', desc: 'Primary identifier' },
    { name: 'first_name / last_name', type: 'string', desc: 'Lead name' },
    { name: 'phone / email', type: 'string', desc: 'Contact info' },
    { name: 'project', type: 'string', desc: 'Interested property project' },
    { name: 'lead_status', type: 'string', desc: 'Pipeline status (New, Contacted, Follow Up 1/2, Interested, Site Visit, etc.)' },
    { name: 'pipeline_category', type: 'string', desc: 'Optional: Qualified, VIP, Nurture, Standard (lead detail UI)' },
    { name: 'temperature', type: 'string', desc: 'Hot / Warm / Cold' },
    { name: 'assigned_to / presales_agent', type: 'string', desc: 'Sales manager' },
    { name: 'context_updates', type: 'array', desc: 'Timeline entries [{type, timestamp, description, agent}]' },
    { name: 'ai_persona_summary', type: 'string', desc: 'Auto-generated persona text' },
    { name: 'created_at / updated_at', type: 'ISO string', desc: 'Timestamps' }
  ]},
  { name: 'users', desc: 'Authentication and user accounts', fields: [
    { name: 'id', type: 'UUID', desc: 'Primary identifier' },
    { name: 'email', type: 'string', desc: 'Login email' },
    { name: 'hashed_password', type: 'string', desc: 'bcrypt hash' },
    { name: 'full_name', type: 'string', desc: 'Display name' },
    { name: 'role', type: 'string', desc: 'User role (admin, agent)' }
  ]},
  { name: 'tasks', desc: 'Follow-up tasks and reminders for leads', fields: [
    { name: 'id', type: 'UUID', desc: 'Primary identifier' },
    { name: 'lead_id', type: 'UUID', desc: 'Associated lead' },
    { name: 'description', type: 'string', desc: 'Task description' },
    { name: 'due_date / due_time', type: 'string', desc: 'When the task is due' },
    { name: 'priority', type: 'string', desc: 'low / medium / high' },
    { name: 'status', type: 'string', desc: 'pending / done' },
    { name: 'assigned_to', type: 'string', desc: 'Responsible person' }
  ]},
  { name: 'notifications', desc: 'System notifications and alerts', fields: [
    { name: 'id', type: 'UUID', desc: 'Primary identifier' },
    { name: 'type', type: 'string', desc: 'rnr_followup, dormant_lead, task_reminder, etc.' },
    { name: 'title / message', type: 'string', desc: 'Notification content' },
    { name: 'lead_id', type: 'UUID', desc: 'Associated lead' },
    { name: 'severity / urgency', type: 'string', desc: 'Priority classification' },
    { name: 'is_read', type: 'boolean', desc: 'Read/unread state' }
  ]},
  { name: 'marketing_spends', desc: 'Marketing spend tracking (dashboard + ROI)', fields: [
    { name: 'id', type: 'UUID', desc: 'Primary identifier' },
    { name: 'project', type: 'string', desc: 'Project name' },
    { name: 'channel', type: 'string', desc: 'meta_ads, google_ads, newspaper, ...' },
    { name: 'amount', type: 'number', desc: 'Spend amount' },
    { name: 'period', type: 'string', desc: 'YYYY-MM' },
    { name: 'leads_generated / conversions', type: 'number', desc: 'Performance counters' }
  ]},
  { name: 'whatsapp_messages', desc: 'WhatsApp chat history (inbound + outbound)', fields: [
    { name: 'id', type: 'UUID', desc: 'Primary identifier' },
    { name: 'direction', type: 'string', desc: 'inbound / outbound' },
    { name: 'source / destination', type: 'string', desc: 'Phone numbers' },
    { name: 'content', type: 'string', desc: 'Message text' },
    { name: 'status', type: 'string', desc: 'submitted / delivered / read / received' }
  ]},
  { name: 'alert_configs', desc: 'Alert rule configurations (6 defaults pre-seeded)', fields: [
    { name: 'id', type: 'UUID', desc: 'Primary identifier' },
    { name: 'name / type', type: 'string', desc: 'Alert name and type identifier' },
    { name: 'description', type: 'string', desc: 'Human-readable description' },
    { name: 'threshold_hours / threshold_days', type: 'integer', desc: 'Trigger threshold' },
    { name: 'is_active', type: 'boolean', desc: 'Enabled/disabled' }
  ]},
  { name: 'webhook_configs', desc: 'Gupshup webhook subscription configurations', fields: [
    { name: 'app_id', type: 'string', desc: 'Gupshup app identifier' },
    { name: 'webhook_url', type: 'string', desc: 'Callback URL' },
    { name: 'status', type: 'string', desc: 'active / inactive' }
  ]}
];

const API_ENDPOINTS = [
  { group: 'Authentication (`/api/auth`)', endpoints: [
    { method: 'POST', path: '/api/auth/register', desc: 'Disabled in production — use admin/create-user or scripts/create_user.py', params: 'JSON: email, password, full_name, phone? (ALLOW_PUBLIC_REGISTRATION=true only)' },
    { method: 'POST', path: '/api/auth/admin/create-user', desc: 'Admin: create user with role', params: 'JSON: email, password, full_name, phone?, role (admin|manager|rep)' },
    { method: 'POST', path: '/api/auth/login', desc: 'OAuth2 password flow — returns access + refresh tokens', params: 'form body: username (email), password' },
    { method: 'GET', path: '/api/auth/me', desc: 'Current user from Bearer JWT', params: 'Authorization: Bearer' },
    { method: 'POST', path: '/api/auth/refresh', desc: 'New access token', params: 'JSON: { refresh_token }' }
  ]},
  { group: 'Leads (`/api/leads`)', endpoints: [
    { method: 'GET', path: '/api/leads', desc: 'List leads (projected payload; trimmed timeline on list only)', params: 'query: project, temperature, budget, location, intent, vip, status, search, days, skip, limit' },
    { method: 'GET', path: '/api/leads/duplicates', desc: 'Duplicate phone groups (scoped)', params: 'query: skip, limit (max 100 groups)' },
    { method: 'POST', path: '/api/leads', desc: 'Create lead', params: 'JSON LeadCreate (first_name, last_name, phone, …)' },
    { method: 'GET', path: '/api/leads/{lead_id}', desc: 'Single lead', params: 'path lead_id' },
    { method: 'PUT', path: '/api/leads/{lead_id}', desc: 'Partial update (LeadUpdatePatch)', params: 'pipeline_category, lead_status, assigned_to, …' },
    { method: 'POST', path: '/api/leads/upload-csv', desc: 'CSV import', params: 'multipart file' },
    { method: 'POST', path: '/api/leads/{lead_id}/merge/{duplicate_id}', desc: 'Merge duplicate into primary', params: 'two lead IDs in path' },
    { method: 'POST', path: '/api/leads/auto-assign', desc: 'Assign to rep with lowest load', params: 'query lead_id' },
    { method: 'POST', path: '/api/leads/{lead_id}/context', desc: 'Append context timeline note', params: 'note, update_type (registered under tasks router)' },
    { method: 'POST', path: '/api/leads/{lead_id}/tasks', desc: 'Create follow-up task', params: 'description, due_date, priority, …' },
    { method: 'GET', path: '/api/leads/{lead_id}/suggestions', desc: 'Project suggestions for lead', params: '-' }
  ]},
  { group: 'Analytics (`/api/analytics`)', endpoints: [
    { method: 'GET', path: '/api/analytics/dashboard', desc: 'Home dashboard KPIs, sources, locations, projects', params: 'query days (optional filter)' },
    { method: 'GET', path: '/api/analytics/sales-dashboard', desc: 'Sales team aggregates + per-manager lead summaries', params: '-' }
  ]},
  { group: 'Marketing (`/api/marketing`)', endpoints: [
    { method: 'GET', path: '/api/marketing/spends', desc: 'List spend rows', params: 'optional project, period' },
    { method: 'POST', path: '/api/marketing/spends', desc: 'Insert into marketing_spends', params: 'project, channel, amount, period, leads_generated, conversions, …' },
    { method: 'GET', path: '/api/marketing/dashboard', desc: 'Aggregated totals, by_project, by_channel, entries', params: '-' },
    { method: 'DELETE', path: '/api/marketing/spends/{spend_id}', desc: 'Remove a spend row', params: 'path id' }
  ]},
  { group: 'Other (notifications, tasks, WhatsApp, alerts)', endpoints: [
    { method: 'GET', path: '/api/notifications', desc: 'Notifications list', params: '…' },
    { method: 'GET', path: '/api/tasks', desc: 'Tasks list', params: 'status, lead_id' },
    { method: 'POST', path: '/api/whatsapp/send-to-lead/{lead_id}', desc: 'WhatsApp to lead', params: 'message body' },
    { method: 'GET/POST', path: '/api/alerts/config', desc: 'Alert rule configs', params: '…' },
    { method: 'GET/POST', path: '/api/assignment-rules', desc: 'Lead assignment rules', params: '…' },
    { method: 'GET/POST', path: '/api/campaigns', desc: 'Legacy AI campaigns API (no UI route in app)', params: 'still available if backend enabled' }
  ]}
];

const ENV_VARS = [
  { name: 'MONGO_URL', desc: 'MongoDB connection string', example: 'mongodb://localhost:27017' },
  { name: 'DB_NAME', desc: 'MongoDB database name', example: 'arihant_crm' },
  { name: 'JWT_SECRET', desc: 'Secret key for JWT token signing', example: '(random string)' },
  { name: 'GUPSHUP_API_KEY', desc: 'Gupshup API key for WhatsApp', example: 'sk_...' },
  { name: 'GUPSHUP_TOKEN', desc: 'Gupshup partner/auth token', example: 'sk_...' },
  { name: 'GUPSHUP_APP_ID', desc: 'Gupshup WhatsApp app ID', example: 'UUID' },
  { name: 'GUPSHUP_SOURCE_PHONE', desc: 'WhatsApp business phone number', example: '919549549339' },
  { name: 'GUPSHUP_APP_NAME', desc: 'Gupshup app name', example: 'ArihantSalesIntelligence' },
  { name: 'VITE_BACKEND_URL', desc: 'Backend API base URL (frontend)', example: 'https://...' }
];

const METHOD_COLORS = { GET: 'bg-green-500/20 text-green-400', POST: 'bg-blue-500/20 text-blue-400', PUT: 'bg-amber-500/20 text-amber-400', DELETE: 'bg-red-500/20 text-red-400', 'GET/POST': 'bg-teal-500/20 text-teal-400' };

const DevDocsPage = () => {
  const [expandedCollections, setExpandedCollections] = useState({});
  const [expandedGroups, setExpandedGroups] = useState({});
  const [copied, setCopied] = useState('');
  const [dbStats, setDbStats] = useState(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const r = await api.get('/analytics/dashboard');
        setDbStats({ leads: r.data.total_leads, hot: r.data.hot_leads, warm: r.data.warm_leads, cold: r.data.cold_leads });
      } catch (e) { /* ignore */ }
    };
    fetchStats();
  }, []);

  const toggle = (key, setter) => setter(prev => ({ ...prev, [key]: !prev[key] }));
  const copy = (text) => { navigator.clipboard.writeText(text); setCopied(text); setTimeout(() => setCopied(''), 2000); };

  return (
    <div className="space-y-3 max-w-5xl">
      <motion.div initial={{ opacity: 0, y: -20 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-xl font-semibold text-white" data-testid="dev-docs-title">Developer Documentation</h1>
        <p className="text-crm-fg-secondary mt-1 text-sm">Technical architecture, database schema, API reference, and data flow</p>
        <p className="text-crm-fg-muted text-sm mt-4 max-w-3xl leading-relaxed">
          The React app talks to a FastAPI backend under the <code className="bg-crm-muted px-1.5 py-0.5 rounded text-[#C5A059] text-xs">/api</code> prefix.
          Authenticate with <code className="bg-crm-muted px-1 rounded text-xs text-[#C5A059]">POST /api/auth/login</code> (form-encoded username/password), store the JWT, then send{' '}
          <code className="bg-crm-muted px-1 rounded text-xs text-[#C5A059]">Authorization: Bearer &lt;token&gt;</code> on all requests below.
          Primary domains: leads (CRM records and timeline), auth, analytics (dashboard + sales rollups), and marketing (spend CRUD + dashboard).
        </p>
      </motion.div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { icon: Database, label: 'Database', value: 'MongoDB', sub: `${COLLECTIONS.length} collections` },
          { icon: Server, label: 'Backend', value: 'FastAPI (Python)', sub: `${API_ENDPOINTS.reduce((a, g) => a + g.endpoints.length, 0)} endpoints` },
          { icon: Globe, label: 'Frontend', value: 'React + Tailwind', sub: 'Shadcn UI components' }
        ].map(c => (
          <div key={c.label} className="glass-card rounded-lg p-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-[#C5A059]/20 flex items-center justify-center"><c.icon className="text-[#C5A059]" size={20} /></div>
            <div>
              <p className="text-white font-medium">{c.value}</p>
              <p className="text-crm-fg-muted text-xs">{c.sub}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Data Flow */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="glass-card rounded-lg p-6">
        <h2 className="font-serif text-xl text-white mb-4 flex items-center gap-2"><Layers className="text-[#C5A059]" size={20} /> Data Flow</h2>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {['Facebook/Website Lead', 'Webhook / CSV Upload', 'leads collection', 'Auto-Assignment Engine', 'Sales Rep Dashboard', 'WhatsApp Follow-up', 'Notifications'].map((step, i) => (
            <React.Fragment key={step}>
              <span className="px-3 py-1.5 bg-crm-muted rounded-lg text-white text-xs border border-crm-border">{step}</span>
              {i < 6 && <ArrowRight size={14} className="text-[#C5A059]" />}
            </React.Fragment>
          ))}
        </div>
      </motion.div>

      {/* Database Schema */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }} className="glass-card rounded-lg p-6">
        <h2 className="font-serif text-xl text-white mb-4 flex items-center gap-2"><Database className="text-[#C5A059]" size={20} /> Database Schema</h2>
        <p className="text-crm-fg-muted text-sm mb-4">MongoDB • Connection: <code className="bg-crm-muted px-2 py-0.5 rounded text-[#C5A059] text-xs">MONGO_URL</code> env var • DB: <code className="bg-crm-muted px-2 py-0.5 rounded text-[#C5A059] text-xs">DB_NAME</code></p>
        <div className="space-y-3">
          {COLLECTIONS.map(col => (
            <div key={col.name} className="border border-white/5 rounded-lg overflow-hidden">
              <button onClick={() => toggle(col.name, setExpandedCollections)} className="w-full flex items-center justify-between p-3 hover:bg-white/5 transition-colors" data-testid={`collection-${col.name}`}>
                <div className="flex items-center gap-3">
                  {expandedCollections[col.name] ? <ChevronDown size={14} className="text-[#C5A059]" /> : <ChevronRight size={14} className="text-crm-fg-muted" />}
                  <code className="text-[#C5A059] text-sm font-medium">{col.name}</code>
                  <span className="text-crm-fg-muted text-xs">— {col.desc}</span>
                </div>
                <span className="text-crm-fg-muted text-xs">{col.fields.length} fields</span>
              </button>
              {expandedCollections[col.name] && (
                <div className="border-t border-white/5 p-3 bg-black/20">
                  <table className="w-full text-xs">
                    <thead><tr className="text-crm-fg-muted"><th className="text-left py-1 px-2">Field</th><th className="text-left py-1 px-2">Type</th><th className="text-left py-1 px-2">Description</th></tr></thead>
                    <tbody>{col.fields.map(f => <tr key={f.name} className="border-t border-white/5"><td className="py-1.5 px-2 text-[#C5A059] font-mono">{f.name}</td><td className="py-1.5 px-2 text-crm-fg-secondary">{f.type}</td><td className="py-1.5 px-2 text-crm-fg-muted">{f.desc}</td></tr>)}</tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      </motion.div>

      {/* API Endpoints */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="glass-card rounded-lg p-6">
        <h2 className="font-serif text-xl text-white mb-4 flex items-center gap-2"><Code className="text-[#C5A059]" size={20} /> API Endpoints</h2>
        <p className="text-crm-fg-muted text-sm mb-4">All endpoints are prefixed with <code className="bg-crm-muted px-2 py-0.5 rounded text-[#C5A059] text-xs">/api</code> • Auth: Bearer JWT token (except webhook)</p>
        <div className="space-y-4">
          {API_ENDPOINTS.map(group => (
            <div key={group.group} className="border border-white/5 rounded-lg overflow-hidden">
              <button onClick={() => toggle(group.group, setExpandedGroups)} className="w-full flex items-center justify-between p-3 hover:bg-white/5 transition-colors">
                <div className="flex items-center gap-3">
                  {expandedGroups[group.group] ? <ChevronDown size={14} className="text-[#C5A059]" /> : <ChevronRight size={14} className="text-crm-fg-muted" />}
                  <span className="text-white text-sm font-medium">{group.group}</span>
                </div>
                <span className="text-crm-fg-muted text-xs">{group.endpoints.length} endpoints</span>
              </button>
              {expandedGroups[group.group] && (
                <div className="border-t border-white/5 divide-y divide-white/5">
                  {group.endpoints.map((ep, i) => (
                    <div key={i} className="p-3 flex items-start gap-3 hover:bg-white/5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold flex-shrink-0 ${METHOD_COLORS[ep.method] || 'bg-gray-500/20 text-gray-400'}`}>{ep.method}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <code className="text-white text-xs font-mono">{ep.path}</code>
                          <button onClick={() => copy(ep.path)} className="text-crm-fg-muted hover:text-[#C5A059]">{copied === ep.path ? <Check size={12} /> : <Copy size={12} />}</button>
                        </div>
                        <p className="text-crm-fg-muted text-xs mt-0.5">{ep.desc}</p>
                        <p className="text-crm-fg-secondary text-[10px] mt-0.5">Params: {ep.params}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </motion.div>

      {/* Environment Variables */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }} className="glass-card rounded-lg p-6">
        <h2 className="font-serif text-xl text-white mb-4 flex items-center gap-2"><Lock className="text-[#C5A059]" size={20} /> Environment Variables</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-crm-fg-muted border-b border-crm-border"><th className="text-left py-2 px-3">Variable</th><th className="text-left py-2 px-3">Description</th><th className="text-left py-2 px-3">Example</th></tr></thead>
            <tbody>{ENV_VARS.map(v => <tr key={v.name} className="border-b border-white/5"><td className="py-2 px-3 text-[#C5A059] font-mono">{v.name}</td><td className="py-2 px-3 text-crm-fg-secondary">{v.desc}</td><td className="py-2 px-3 text-crm-fg-muted">{v.example}</td></tr>)}</tbody>
          </table>
        </div>
      </motion.div>
    </div>
  );
};

export default DevDocsPage;
