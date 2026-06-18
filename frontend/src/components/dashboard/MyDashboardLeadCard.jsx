import React, { memo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRightLeft, Eye, Calendar,
  User, Building,
  ListChecks,
} from 'lucide-react';
import { Button } from '../ui/button';
import { LeadStatusBadge } from '../leads/LeadStatusBadge';
import { CrmBadge } from '../ui/CrmBadge';
import { getLeadInitials } from '../../utils/leadTable';

export const MyDashboardLeadCard = memo(function MyDashboardLeadCard({
  lead,
  followUp,
  taskCount,
  isManager,
  onTransfer,
  onOpenTasks,
}) {
  const navigate = useNavigate();

  const openLead = () => navigate(`/lead/${lead.id}`);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openLead();
    }
  };

  const stop = (e) => e.stopPropagation();

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={openLead}
      onKeyDown={handleKeyDown}
      className="bg-[#1A1A1A] border border-white/5 rounded-lg p-3 hover:border-white/10 hover:bg-white/[0.02] transition-all group cursor-pointer"
      data-testid={`lead-card-${lead.id}`}
    >
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-[#C5A059]/15 flex items-center justify-center flex-shrink-0 text-[#C5A059] text-xs font-semibold">
          {getLeadInitials(lead)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-white font-medium text-sm truncate">
              {lead.first_name} {lead.last_name}
            </p>
            {lead.vip && (
              <CrmBadge variant="gold" size="xs">
                VIP
              </CrmBadge>
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
            <LeadStatusBadge status={lead.lead_status} temperature={lead.temperature} />
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
                <button
                  type="button"
                  className="inline-flex items-center hover:opacity-90"
                  onClick={(e) => {
                    stop(e);
                    onOpenTasks?.(lead);
                  }}
                  data-testid={`lead-card-tasks-${lead.id}`}
                >
                  <CrmBadge variant="warning" size="xs">
                    {taskCount} pending
                  </CrmBadge>
                </button>
              ) : (
                <span className="text-[#52525B]">—</span>
              )}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity" onClick={stop}>
          <Button
            size="sm"
            variant="ghost"
            className="text-[#A1A1AA] hover:text-white h-8 w-8 p-0"
            onClick={openLead}
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
