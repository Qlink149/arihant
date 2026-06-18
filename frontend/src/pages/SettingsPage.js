import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { alertsAPI, remindersAPI, settingsAPI } from '../services/api';
import { toast } from 'sonner';
import { formatDateTimeIST } from '../utils/datetime';
import {
  Bell,
  Clock,
  Mail,
  MessageCircle,
  Plus,
  Save,
  Trash2,
  ChevronDown,
  AlertTriangle,
  History,
  Zap,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Switch } from '../components/ui/switch';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
const SettingsPage = () => {
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState([]);
  const [pendingAlerts, setPendingAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAddAlert, setShowAddAlert] = useState(false);
  const [reminderRules, setReminderRules] = useState([]);
  const [reminderHistory, setReminderHistory] = useState([]);
  const [triggering, setTriggering] = useState(false);
  const [brevo, setBrevo] = useState({
    brevo_enabled: false,
    brevo_api_key: '',
    alert_email: '',
    sender_email: '',
    dashboard_url: '',
  });
  const [savingBrevo, setSavingBrevo] = useState(false);

  // New alert form
  const [newAlert, setNewAlert] = useState({
    alert_type: 'rnr_followup',
    threshold_hours: 24,
    notification_channels: ['email'],
    is_active: true
  });

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [alertsRes, pendingRes, remRulesRes, remHistRes, brevoRes] = await Promise.all([
        alertsAPI.getConfig(),
        alertsAPI.getPending(),
        remindersAPI.getRules(),
        remindersAPI.getHistory(20),
        settingsAPI.getBrevo().catch(() => ({ data: {} })),
      ]);
      setAlerts(alertsRes.data);
      setPendingAlerts(pendingRes.data);
      setReminderRules(remRulesRes.data || []);
      setReminderHistory(remHistRes.data || []);
      if (brevoRes?.data) setBrevo((p) => ({ ...p, ...brevoRes.data }));
    } catch (error) {
      console.error('Failed to fetch settings:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAddAlert = async () => {
    try {
      await alertsAPI.createConfig(newAlert);
      toast.success('Alert configuration added');
      setShowAddAlert(false);
      fetchData();
    } catch (error) {
      toast.error('Failed to add alert');
    }
  };

  const handleToggleReminder = async (ruleId, currentActive) => {
    try {
      await remindersAPI.updateRule(ruleId, { is_active: !currentActive });
      setReminderRules(prev => prev.map(r => r.id === ruleId ? { ...r, is_active: !currentActive } : r));
      toast.success(`Rule ${!currentActive ? 'enabled' : 'disabled'}`);
    } catch {
      toast.error('Failed to update rule');
    }
  };

  const handleToggleWhatsApp = async (ruleId, currentWA) => {
    try {
      await remindersAPI.updateRule(ruleId, { send_whatsapp: !currentWA });
      setReminderRules(prev => prev.map(r => r.id === ruleId ? { ...r, send_whatsapp: !currentWA } : r));
      toast.success(`WhatsApp ${!currentWA ? 'enabled' : 'disabled'} for this rule`);
    } catch {
      toast.error('Failed to update');
    }
  };

  const handleTriggerReminders = async () => {
    setTriggering(true);
    try {
      const res = await remindersAPI.triggerNow();
      toast.success(res.data.message || 'Reminders triggered');
      // Refresh history
      const histRes = await remindersAPI.getHistory(20);
      setReminderHistory(histRes.data || []);
    } catch {
      toast.error('Failed to trigger reminders');
    } finally {
      setTriggering(false);
    }
  };

  const alertTypes = [
    { value: 'rnr_followup', label: 'RNR Follow-up', description: 'Alert when RNR leads need follow-up' },
    { value: 'lead_update', label: 'Lead Update', description: 'Alert when leads are not updated' },
    { value: 'intent_notification', label: 'Intent Notification', description: 'Notify on high/low intent detection' }
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-[#C5A059] animate-pulse">Loading settings...</div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <h1 className="text-xl font-semibold text-white" data-testid="settings-title">
          Settings
        </h1>
        <p className="text-[#A1A1AA] mt-2">Configure alerts and notifications</p>
      </motion.div>

      {/* Pending Alerts Banner */}
      {pendingAlerts.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-card rounded-lg p-4 border-l-4 border-orange-500"
          data-testid="pending-alerts"
        >
          <div className="flex items-center gap-3">
            <AlertTriangle className="text-orange-500" size={24} />
            <div>
              <p className="text-white font-medium">
                {pendingAlerts.length} pending alert{pendingAlerts.length > 1 ? 's' : ''}
              </p>
              <p className="text-[#A1A1AA] text-sm">
                {pendingAlerts.filter(a => a.type === 'rnr_followup').length} RNR follow-ups needed
              </p>
            </div>
          </div>
        </motion.div>
      )}

      {/* Alert Configurations */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass-card rounded-lg p-6"
      >
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-[#C5A059]/20 flex items-center justify-center">
              <Bell className="text-[#C5A059]" size={20} />
            </div>
            <div>
              <h2 className="font-serif text-xl text-white">Alert Configurations</h2>
              <p className="text-[#52525B] text-sm">Manage notification rules for your team</p>
            </div>
          </div>
          <Button
            onClick={() => setShowAddAlert(true)}
            className="bg-[#C5A059] text-black hover:bg-[#E5C079]"
            data-testid="add-alert-btn"
          >
            <Plus size={16} className="mr-2" />
            Add Alert
          </Button>
        </div>

        <div className="space-y-4">
          {alerts.length === 0 ? (
            <div className="text-center py-8 text-[#52525B]">
              No alert configurations yet. Add one to get started.
            </div>
          ) : (
            alerts.map((alert, idx) => (
              <div
                key={alert.id || idx}
                className="flex items-center justify-between p-4 bg-black/30 rounded-lg"
                data-testid={`alert-config-${idx}`}
              >
                <div className="flex items-center gap-4">
                  <div className={`w-3 h-3 rounded-full ${alert.is_active ? 'bg-green-500' : 'bg-gray-500'}`} />
                  <div>
                    <p className="text-white font-medium">
                      {alert.name || alertTypes.find(t => t.value === alert.alert_type)?.label || alert.type || alert.alert_type}
                    </p>
                    <p className="text-[#52525B] text-sm">
                      {alert.description || `Threshold: ${alert.threshold_hours || alert.threshold_days || 0}${alert.threshold_days ? ' days' : 'h'} • Channels: ${(alert.notification_channels || []).join(', ') || 'In-app'}`}
                    </p>
                  </div>
                </div>
                <Switch checked={alert.is_active} />
              </div>
            ))
          )}
        </div>
      </motion.div>

      {/* Notification Channels */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="glass-card rounded-lg p-6"
      >
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-[#C5A059]/20 flex items-center justify-center">
            <MessageCircle className="text-[#C5A059]" size={20} />
          </div>
          <div>
            <h2 className="font-serif text-xl text-white">Notification Channels</h2>
            <p className="text-[#52525B] text-sm">Configure how you receive alerts</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="flex items-center justify-between p-4 bg-black/30 rounded-lg">
            <div className="flex items-center gap-3">
              <Mail className="text-[#C5A059]" size={20} />
              <span className="text-white">Email</span>
            </div>
            <Switch defaultChecked />
          </div>
          <div className="flex items-center justify-between p-4 bg-black/30 rounded-lg">
            <div className="flex items-center gap-3">
              <MessageCircle className="text-green-500" size={20} />
              <span className="text-white">WhatsApp</span>
            </div>
            <Switch />
          </div>
          <div className="flex items-center justify-between p-4 bg-black/30 rounded-lg">
            <div className="flex items-center gap-3">
              <Bell className="text-blue-500" size={20} />
              <span className="text-white">Push Notifications</span>
            </div>
            <Switch />
          </div>
        </div>
      </motion.div>

      {/* Add Alert Dialog */}
      <Dialog open={showAddAlert} onOpenChange={setShowAddAlert}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl">Add Alert Configuration</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-[#A1A1AA] text-sm mb-2 block">Alert Type</label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    className="w-full justify-between bg-black/50 border-white/10 text-white"
                  >
                    {alertTypes.find(t => t.value === newAlert.alert_type)?.label || 'Select type'}
                    <ChevronDown size={14} />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="bg-[#1A1A1A] border-white/10">
                  {alertTypes.map((type) => (
                    <DropdownMenuItem
                      key={type.value}
                      onClick={() => setNewAlert({ ...newAlert, alert_type: type.value })}
                      className="text-white hover:bg-[#C5A059]/10 cursor-pointer"
                    >
                      {type.label}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <div>
              <label className="text-[#A1A1AA] text-sm mb-2 block">Threshold (hours)</label>
              <Input
                type="number"
                value={newAlert.threshold_hours}
                onChange={(e) => setNewAlert({ ...newAlert, threshold_hours: parseInt(e.target.value) })}
                className="bg-black/50 border-white/10 text-white"
              />
            </div>

            <div>
              <label className="text-[#A1A1AA] text-sm mb-2 block">Notification Channels</label>
              <div className="flex gap-2">
                {['email', 'whatsapp', 'sms'].map((channel) => (
                  <Button
                    key={channel}
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      const channels = newAlert.notification_channels.includes(channel)
                        ? newAlert.notification_channels.filter(c => c !== channel)
                        : [...newAlert.notification_channels, channel];
                      setNewAlert({ ...newAlert, notification_channels: channels });
                    }}
                    className={`capitalize ${
                      newAlert.notification_channels.includes(channel)
                        ? 'bg-[#C5A059] text-black border-[#C5A059]'
                        : 'bg-transparent border-white/10 text-white'
                    }`}
                  >
                    {channel}
                  </Button>
                ))}
              </div>
            </div>

            <Button
              onClick={handleAddAlert}
              className="w-full bg-[#C5A059] text-black hover:bg-[#E5C079]"
            >
              <Save size={16} className="mr-2" />
              Save Alert
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ==================== AUTOMATED REMINDERS ==================== */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="glass-card rounded-lg p-6"
        data-testid="reminders-section"
      >
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center">
              <Zap size={20} className="text-purple-400" />
            </div>
            <div>
              <h2 className="text-xl text-white font-medium">Automated Reminders</h2>
              <p className="text-[#A1A1AA] text-sm">SOP-driven reminders via WhatsApp & in-app notifications</p>
            </div>
          </div>
          <Button
            onClick={handleTriggerReminders}
            disabled={triggering}
            className="bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 border border-purple-500/30"
            data-testid="trigger-reminders-btn"
          >
            <Play size={14} className="mr-2" />
            {triggering ? 'Running...' : 'Run Now'}
          </Button>
        </div>

        {/* Reminder Rules */}
        <div className="space-y-3 mb-6">
          {reminderRules.map((rule) => (
            <div
              key={rule.id}
              className={`bg-black/30 rounded-lg p-4 border ${rule.is_active ? 'border-purple-500/20' : 'border-white/5 opacity-60'}`}
              data-testid={`reminder-rule-${rule.id}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-white font-medium text-sm">{rule.name}</p>
                    {rule.days_threshold > 0 && (
                      <span className="text-[10px] bg-white/10 text-[#A1A1AA] px-1.5 py-0.5 rounded-full">
                        {rule.days_threshold}d threshold
                      </span>
                    )}
                  </div>
                  <p className="text-[#52525B] text-xs mt-0.5">
                    Trigger: <span className="text-[#A1A1AA]">{rule.trigger.replace(/_/g, ' ')}</span>
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2">
                    <MessageCircle size={14} className={rule.send_whatsapp ? 'text-green-400' : 'text-[#52525B]'} />
                    <Switch
                      checked={rule.send_whatsapp}
                      onCheckedChange={() => handleToggleWhatsApp(rule.id, rule.send_whatsapp)}
                      data-testid={`wa-toggle-${rule.id}`}
                    />
                  </div>
                  <Switch
                    checked={rule.is_active}
                    onCheckedChange={() => handleToggleReminder(rule.id, rule.is_active)}
                    data-testid={`active-toggle-${rule.id}`}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Reminder History */}
        <div>
          <h3 className="text-white font-medium text-sm flex items-center gap-2 mb-3">
            <History size={14} className="text-[#C5A059]" /> Recent Reminders
          </h3>
          {reminderHistory.length === 0 ? (
            <p className="text-[#52525B] text-sm text-center py-4">No reminders sent yet. Click "Run Now" to trigger.</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {reminderHistory.map((r) => (
                <div key={r.id} className="flex items-start gap-3 py-2 border-b border-white/5 last:border-0">
                  <div className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${r.whatsapp_sent ? 'bg-green-400' : 'bg-[#52525B]'}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-[#A1A1AA] text-xs">{r.message}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[#52525B] text-[10px]">{r.assigned_to}</span>
                      <span className="text-[#52525B] text-[10px]">{formatDateTimeIST(r.created_at) || '—'}</span>
                      {r.whatsapp_sent && <span className="text-green-400 text-[10px]">WA sent</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card rounded-xl p-6 border border-white/10 space-y-4"
      >
        <h2 className="font-serif text-xl text-white flex items-center gap-2">
          <Mail className="text-[#C5A059]" size={20} />
          Brevo (Admin alerts)
        </h2>
        <p className="text-[#52525B] text-sm">
          Nurturing 14-day review digest. Create template <code className="text-[#A1A1AA]">nurturing_review_alert</code> in Brevo or use default HTML body.
        </p>
        <div className="flex items-center justify-between">
          <span className="text-[#A1A1AA] text-sm">Enable Brevo</span>
          <Switch
            checked={brevo.brevo_enabled}
            onCheckedChange={(v) => setBrevo((p) => ({ ...p, brevo_enabled: v }))}
          />
        </div>
        <Input
          placeholder="Alert email"
          value={brevo.alert_email}
          onChange={(e) => setBrevo((p) => ({ ...p, alert_email: e.target.value }))}
          className="bg-[#0F0F0F] border-white/10 text-white"
        />
        <Input
          placeholder="API key (leave *** to keep)"
          value={brevo.brevo_api_key}
          onChange={(e) => setBrevo((p) => ({ ...p, brevo_api_key: e.target.value }))}
          className="bg-[#0F0F0F] border-white/10 text-white"
        />
        <Input
          placeholder="Dashboard URL"
          value={brevo.dashboard_url}
          onChange={(e) => setBrevo((p) => ({ ...p, dashboard_url: e.target.value }))}
          className="bg-[#0F0F0F] border-white/10 text-white"
        />
        <div className="flex gap-2">
          <Button
            className="bg-[#C5A059] text-black"
            disabled={savingBrevo}
            onClick={async () => {
              setSavingBrevo(true);
              try {
                await settingsAPI.updateBrevo(brevo);
                toast.success('Settings saved');
              } catch {
                toast.error('Save failed (admin only)');
              } finally {
                setSavingBrevo(false);
              }
            }}
          >
            <Save size={14} className="mr-2" />
            Save
          </Button>
          <Button
            variant="outline"
            className="border-white/10 text-white"
            onClick={async () => {
              try {
                const { data } = await settingsAPI.testBrevo();
                toast[data?.ok ? 'success' : 'error'](data?.ok ? 'Test email sent' : 'Test failed');
              } catch {
                toast.error('Test send failed');
              }
            }}
          >
            Test send
          </Button>
        </div>
      </motion.div>
    </div>
  );
};

export default SettingsPage;
