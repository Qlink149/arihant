import {

  Target,

  Calendar,

  CalendarClock,

  AlertCircle,

  PhoneOff,

  MapPin,

  CheckCircle2,

  Trash2,

  Snowflake,

  RefreshCw,

  ArrowDownLeft,

  ArrowUpRight,

} from 'lucide-react';



export const METRIC_LABELS = {

  all_leads: 'All leads',

  todays_leads: "Today's leads",

  follow_up_today: 'Follow up today',

  missed_follow_up: 'Missed follow up',

  rnr: 'RNR',

  todays_site_visits: "Today's site visits",

  sv_conducted: 'SV conducted',

  junk: 'Junk',

  gone_cold: 'Gone cold',

  re_engaged: 'Re-engaged',

  active_pipeline: 'Active pipeline',

  qualified_leads: 'Active pipeline',

  negotiation: 'In negotiation',

  site_visits: 'Site visit stage',

  deals_won: 'Deals won',

  deals_lost: 'Deals lost',

  contacted: 'Contacted',

  leads_received: 'Leads received',

  leads_transferred: 'Leads transferred',

  dormant: 'Dormant leads',

};



export const ACCENT_STYLES = {

  gold: { bar: 'bg-[#C5A059]', icon: Target, iconClass: 'text-[#C5A059]' },

  teal: { bar: 'bg-teal-500', icon: Calendar, iconClass: 'text-teal-400' },

  amber: { bar: 'bg-amber-500', icon: CalendarClock, iconClass: 'text-amber-400' },

  red: { bar: 'bg-red-500', icon: AlertCircle, iconClass: 'text-red-400' },

  purple: { bar: 'bg-purple-500', icon: MapPin, iconClass: 'text-purple-400' },

  green: { bar: 'bg-emerald-500', icon: CheckCircle2, iconClass: 'text-emerald-400' },

  slate: { bar: 'bg-zinc-500', icon: Trash2, iconClass: 'text-zinc-400' },

  blue: { bar: 'bg-blue-500', icon: RefreshCw, iconClass: 'text-blue-400' },

};



const KEY_ICON_FALLBACK = {

  all_leads: Target,

  todays_leads: Calendar,

  follow_up_today: CalendarClock,

  missed_follow_up: AlertCircle,

  rnr: PhoneOff,

  todays_site_visits: MapPin,

  sv_conducted: CheckCircle2,

  junk: Trash2,

  gone_cold: Snowflake,

  re_engaged: RefreshCw,

  active_pipeline: Target,

  qualified_leads: Target,

  leads_received: ArrowDownLeft,

  leads_transferred: ArrowUpRight,

};



export function getAccentStyle(metric) {

  const accent = metric?.accent || 'gold';

  const base = ACCENT_STYLES[accent] || ACCENT_STYLES.gold;

  const Icon = KEY_ICON_FALLBACK[metric?.key] || base.icon;

  return { ...base, Icon };

}



export function buildVirtualCustomerPath(params = {}) {

  const metric = params.metric;

  if (!metric) return '/virtual-customer';

  return `/virtual-customer?metric=${encodeURIComponent(metric)}`;

}



/**

 * @param {object} drillDown - { type, params }

 * @param {{ navigate, setActiveTab, setTransferSubTab }} handlers

 */

export function resolveDrillDown(drillDown, handlers) {

  if (!drillDown?.type) return;



  const { type, params = {} } = drillDown;



  if (type === 'virtual_customer') {

    handlers.navigate?.(buildVirtualCustomerPath(params));

    return;

  }



  if (type === 'my_dashboard_transfers') {
    const subTab = params.sub_tab === 'sent' ? 'sent' : 'received';
    if (handlers.setActiveTab) {
      handlers.setActiveTab('transfers');
      handlers.setTransferSubTab?.(subTab);
      return;
    }
    handlers.navigate?.('/my-dashboard', {
      state: { activeTab: 'transfers', transferSubTab: subTab },
    });
    return;
  }

}


