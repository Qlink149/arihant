import React, { memo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRightLeft, Eye, Calendar,
  User, Building,
  ListChecks,
} from 'lucide-react';
import { Button } from '../ui/button';
import { TemperatureBadge } from '../leads/TemperatureBadge';
import { getLeadInitials } from '../../utils/leadTable';

const STATUS_COLORS = {
  'Open': 'bg-blue-500/20 text-blue-400',
  'Follow Up 1': 'bg-amber-500/20 text-amber-400',
  'Follow Up 2': 'bg-amber-600/20 text-amber-500',
  'Site Visit Scheduled': 'bg-purple-500/20 text-purple-400',
  'Visit Completed': 'bg-green-500/20 text-green-400',
  'SV Completed – Follow Up': 'bg-teal-500/20 text-teal-400',
  'Re-engaged': 'bg-cyan-500/20 text-cyan-400',
  'Negotiation': 'bg-amber-500/20 text-amber-400',
  'Advance Paid': 'bg-emerald-500/20 text-emerald-400',
  'RNR': 'bg-red-500/20 text-red-400',
  'Nurturing': 'bg-orange-500/20 text-orange-400',
  'Gone Cold': 'bg-gray-500/20 text-gray-400',
};

export const MyDashboardLeadCard = memo(function MyDashboardLeadCard({
  lead,
  followUp,
  taskCount,
  statusDisplay,
  isManager,
  onTransfer,
}) {
  const navigate = useNavigate();

  return (
    <div
      className="bg-[#1A1A1A] border border-white/5 rounded-xl p-4 hover:border-white/10 transition-all group"
      data-testid={`lead-card-${lead.id}`}
    >
      <div className="flex items-center gap-4">
        <div className="w-10 h-10 rounded-lg bg-[#C5A059]/15 flex items-center justify-center flex-shrink-0 text-[#C5A059] text-xs font-semibold">
          {getLeadInitials(lead)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-white font-medium text-sm truncate">
              {lead.first_name} {lead.last_name}
            </p>
            {lead.vip && (
              <span className="text-[10px] bg-[#C5A059]/20 text-[#C5A059] px-1.5 py-0.5 rounded-full">
                VIP
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-[#52525B] text-xs flex items-center gap-1">
              <Building size={11} /> {lead.project || 'No project'}
            </span>
            {isManager && (lead.assigned_to || lead.assigned_to_name) && (
              <span className="text-[#52525B] text-xs flex items-center gap-1">
                <User size={11} /> {lead.assigned_to || lead.assigned_to_name}
              </span>
            )}
            {lead.lead_status === 'Nurturing' && (lead.temperature === 'Hot' || lead.temperature === 'Warm') ? (
              <span className="inline-flex items-center gap-1.5">
                <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[lead.lead_status] || 'bg-gray-500/20 text-gray-400'}`}>
                  Nurturing
                </span>
                <TemperatureBadge temperature={lead.temperature} />
              </span>
            ) : (
              <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[lead.lead_status] || 'bg-gray-500/20 text-gray-400'}`}>
                {statusDisplay}
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3 mt-2">
            <span className="text-[#A1A1AA] text-xs flex items-center gap-1">
              <Calendar size={11} className="text-[#52525B]" />
              {followUp ? (
                <span className="text-white/90 font-medium">{followUp}</span>
              ) : (
                <span className="text-[#52525B]">—</span>
              )}
            </span>
            <span className="text-[#A1A1AA] text-xs flex items-center gap-1">
              <ListChecks size={11} className="text-[#52525B]" />
              {taskCount > 0 ? (
                <span className="text-amber-300 font-medium">{taskCount} pending</span>
              ) : (
                <span className="text-[#52525B]">—</span>
              )}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <Button
            size="sm"
            variant="ghost"
            className="text-[#A1A1AA] hover:text-white h-8 w-8 p-0"
            onClick={() => navigate(`/lead/${lead.id}`)}
            data-testid={`view-lead-${lead.id}`}
          >
            <Eye size={16} />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-[#A1A1AA] hover:text-amber-400 h-8 w-8 p-0"
            onClick={() => onTransfer(lead)}
            data-testid={`transfer-lead-${lead.id}`}
          >
            <ArrowRightLeft size={16} />
          </Button>
        </div>
      </div>
    </div>
  );
});
