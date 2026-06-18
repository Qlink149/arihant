import React, { useState, useEffect, useMemo, memo, useCallback } from 'react';
import { motion } from 'framer-motion';
import { DollarSign, Home, Calendar, MapPin, Target, Pencil, Sparkles, Building, Briefcase, Phone, Link2, Ruler, Hash, CheckCircle, Clock } from 'lucide-react';
import { toast } from 'sonner';
import { leadsAPI } from '../../services/api';
import { Button } from '../ui/button';
import { CrmBadge } from '../ui/CrmBadge';
import { Input } from '../ui/input';
import {
  CANONICAL_LOCATIONS,
  CANONICAL_PROJECTS,
  CANONICAL_SOURCES,
  mergePicklistWithApi,
  picklistNames,
} from '../../constants/leadPicklists';
import { formatDateTimeIST } from '../../utils/datetime';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '../ui/accordion';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import {
  OTHER_OPTION_VALUE,
  normalizeOptions,
  resolveSelectWithOtherState,
  resolveSelectWithOtherValue,
} from '../../utils/selectWithOther';

const BUDGET_RANGES = ['Under 1Cr', '1-2 Cr', '2-5 Cr', '5 Cr+'];
const PURPOSE_OPTIONS = ['Investor', 'Self-Occupation', 'Not Decided'];

const formatMetaQualified = (value) => {
  if (value === true) return 'Yes';
  if (value === false) return 'No';
  return 'Not set';
};

const FIELD_CONFIG = [
  {
    id: 'project',
    label: 'Project',
    icon: Building,
    apiKey: 'project',
    aiKey: null,
    type: 'project',
    display: (lead) => lead.project || 'Not specified',
  },
  {
    id: 'budget',
    label: 'Budget',
    icon: DollarSign,
    apiKey: 'budget',
    aiKey: 'budget',
    type: 'budget',
    display: (lead) => lead.budget || 'Not specified',
  },
  {
    id: 'configuration',
    label: 'Configuration',
    icon: Home,
    apiKey: 'configuration',
    aiKey: 'configuration',
    type: 'text',
    display: (lead) => lead.configuration || 'Not specified',
  },
  {
    id: 'possession',
    label: 'Possession',
    icon: Calendar,
    apiKey: 'possession_requirement',
    aiKey: 'possession_requirement',
    type: 'text',
    display: (lead) => lead.possession_requirement || 'Not specified',
  },
  {
    id: 'location',
    label: 'Location Interested',
    icon: MapPin,
    apiKey: 'location',
    aiKey: null,
    type: 'location',
    display: (lead) => lead.location || 'Not specified',
  },
  {
    id: 'purpose',
    label: 'Purpose',
    icon: Target,
    apiKey: 'reason_for_purchase',
    aiKey: 'intent',
    type: 'purpose',
    display: (lead) => lead.reason_for_purchase || lead.intent || 'Unknown',
  },
  {
    id: 'designation',
    label: 'Designation',
    icon: Briefcase,
    apiKey: 'designation',
    aiKey: null,
    type: 'text',
    display: (lead) => lead.designation || 'Not specified',
  },
  {
    id: 'residence',
    label: 'Residence',
    icon: Home,
    apiKey: 'current_residence_type',
    aiKey: null,
    type: 'text',
    display: (lead) => lead.current_residence_type || 'Not specified',
  },
  {
    id: 'mobile',
    label: 'Mobile',
    icon: Phone,
    apiKey: 'phone',
    aiKey: null,
    type: 'text',
    display: (lead) => lead.phone || 'Not specified',
  },
  {
    id: 'work',
    label: 'Work',
    icon: Phone,
    apiKey: 'work_phone',
    aiKey: null,
    type: 'text',
    display: (lead) => lead.work_phone || 'Not specified',
  },
  {
    id: 'source',
    label: 'Source',
    icon: Link2,
    apiKey: 'lead_source',
    aiKey: null,
    type: 'source',
    display: (lead) => lead.lead_source || 'Not specified',
  },
  {
    id: 'original_source',
    label: 'Original source',
    icon: Link2,
    apiKey: 'original_source',
    aiKey: null,
    type: 'text',
    display: (lead) => lead.original_source || 'Not specified',
  },
  {
    id: 'most_recent_source',
    label: 'Most recent source',
    icon: Link2,
    apiKey: 'most_recent_source',
    aiKey: null,
    type: 'text',
    display: (lead) => lead.most_recent_source || 'Not specified',
  },
  {
    id: 'unit_size',
    label: 'Unit Size',
    icon: Ruler,
    apiKey: 'unit_size',
    aiKey: null,
    type: 'text',
    display: (lead) => lead.unit_size || 'Not specified',
  },
  {
    id: 'site_visits',
    label: 'No. of Site Visits',
    icon: Hash,
    apiKey: 'site_visit_count',
    aiKey: null,
    type: 'number',
    display: (lead) => {
      const n = lead.site_visit_count;
      return n === 0 || n ? String(n) : '0';
    },
  },
  {
    id: 'meta_qualified',
    label: 'Meta Qualified',
    icon: CheckCircle,
    apiKey: 'meta_qualified',
    aiKey: null,
    type: 'meta_qualified',
    display: (lead) => formatMetaQualified(lead.meta_qualified),
  },
  {
    id: 'created_at',
    label: 'Created at',
    icon: Clock,
    apiKey: 'created_at',
    aiKey: null,
    type: 'readonly_datetime',
    readonly: true,
    display: (lead) => formatDateTimeIST(lead.created_at) || '—',
  },
  {
    id: 'updated_at',
    label: 'Updated at',
    icon: Clock,
    apiKey: 'updated_at',
    aiKey: null,
    type: 'readonly_datetime',
    readonly: true,
    display: (lead) => formatDateTimeIST(lead.updated_at) || '—',
  },
];

function getAiValue(lead, aiKey) {
  if (!aiKey) return null;
  const val = lead?.ai_grounded_profile?.[aiKey];
  if (!val || val === 'Not specified' || val === 'Unknown') return null;
  return val;
}

function formatLeadNumber(id) {
  if (!id) return '—';
  const raw = String(id).replace(/-/g, '').toUpperCase();
  return raw.length > 8 ? raw.slice(0, 8) : raw;
}

const DataDnaCard = memo(function DataDnaCard({ field, lead, onEdit, index }) {
  const aiValue = getAiValue(lead, field.aiKey);
  const value = field.display(lead);

  if (field.readonly) {
    return (
      <div
        className="lead-overview-field flex items-start gap-2 py-2 px-3 rounded-md w-full text-left relative opacity-90"
        data-testid={`data-dna-${field.id}`}
      >
        <span
          className="lead-overview-index shrink-0 w-5 h-5 rounded text-[10px] font-medium flex items-center justify-center mt-0.5"
          aria-hidden
        >
          {index}
        </span>
        <span className="text-[#52525B] text-[10px] uppercase tracking-wider shrink-0 w-[76px] pt-0.5">
          {field.label}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-white text-sm font-medium truncate">{value}</p>
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onEdit(field)}
      className="lead-overview-field group flex items-start gap-2 py-2 px-3 rounded-md transition-all w-full text-left relative"
      data-testid={`data-dna-${field.id}`}
    >
      <Pencil
        size={10}
        className="absolute top-1.5 right-1.5 text-[#52525B] opacity-0 group-hover:opacity-100 transition-opacity"
      />
      <span
        className="lead-overview-index shrink-0 w-5 h-5 rounded text-[10px] font-medium flex items-center justify-center mt-0.5"
        aria-hidden
      >
        {index}
      </span>
      <span className="text-[#52525B] text-[10px] uppercase tracking-wider shrink-0 w-[76px] pt-0.5">
        {field.label}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-white text-sm font-medium truncate">{value}</p>
        {aiValue && (
          <p className="text-[#737373] text-[10px] mt-0.5 truncate" title={`AI: ${aiValue}`}>
            AI: {aiValue}
          </p>
        )}
      </div>
    </button>
  );
});

function NativeSelectWithOther({
  optionNames,
  mode,
  presetValue,
  otherText,
  onModeChange,
  onPresetChange,
  onOtherTextChange,
  placeholder,
  otherPlaceholder,
  disabled = false,
}) {
  const selectValue = mode === 'other' ? OTHER_OPTION_VALUE : presetValue || '';

  return (
    <div className="space-y-3">
      <select
        value={selectValue}
        onChange={(e) => {
          if (e.target.value === OTHER_OPTION_VALUE) {
            onModeChange('other');
            onPresetChange('');
            return;
          }
          onModeChange('preset');
          onPresetChange(e.target.value);
        }}
        className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm"
        disabled={disabled}
      >
        <option value="">{placeholder}</option>
        {optionNames.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
        <option value={OTHER_OPTION_VALUE}>Other</option>
      </select>
      {mode === 'other' && (
        <Input
          value={otherText}
          onChange={(e) => {
            onModeChange('other');
            onOtherTextChange(e.target.value);
          }}
          placeholder={otherPlaceholder}
          className="bg-black/50 border-white/10 text-white"
          disabled={disabled}
        />
      )}
    </div>
  );
}

export function DataDnaGrid({ lead, leadId, onLeadUpdated, sticky = true, stickySummaryVisible = false }) {
  const [overviewOpen, setOverviewOpen] = useState(undefined);

  useEffect(() => {
    setOverviewOpen(undefined);
  }, [leadId]);
  const [editingField, setEditingField] = useState(null);
  const [draftValue, setDraftValue] = useState('');
  const [selectMode, setSelectMode] = useState('preset');
  const [presetValue, setPresetValue] = useState('');
  const [otherText, setOtherText] = useState('');
  const [saving, setSaving] = useState(false);
  const [locations, setLocations] = useState([]);
  const [projects, setProjects] = useState([]);
  const [sources, setSources] = useState([]);
  const [loadingOptions, setLoadingOptions] = useState(false);

  useEffect(() => {
    if (!editingField || !['location', 'project', 'source'].includes(editingField.type)) return undefined;
    let alive = true;
    setLoadingOptions(true);
    leadsAPI
      .getFilterOptions()
      .then(({ data }) => {
        if (!alive) return;
        setLocations(mergePicklistWithApi(CANONICAL_LOCATIONS, data?.locations || []));
        setProjects(mergePicklistWithApi(CANONICAL_PROJECTS, data?.projects || []));
        setSources(mergePicklistWithApi(CANONICAL_SOURCES, data?.sources || []));
      })
      .catch(() => {
        if (!alive) return;
        setLocations(mergePicklistWithApi(CANONICAL_LOCATIONS, []));
        setProjects(mergePicklistWithApi(CANONICAL_PROJECTS, []));
        setSources(mergePicklistWithApi(CANONICAL_SOURCES, []));
      })
      .finally(() => {
        if (!alive) return;
        setLoadingOptions(false);
      });
    return () => { alive = false; };
  }, [editingField]);

  useEffect(() => {
    if (!editingField || loadingOptions) return;
    if (!['location', 'project', 'source'].includes(editingField.type)) return;
    const current = lead[editingField.apiKey] || '';
    const options =
      editingField.type === 'location'
        ? locations
        : editingField.type === 'project'
          ? projects
          : sources;
    const next = resolveSelectWithOtherState(current, normalizeOptions(options));
    setSelectMode(next.mode);
    setPresetValue(next.presetValue);
    setOtherText(next.otherText);
  }, [editingField, locations, projects, sources, loadingOptions, lead]);

  const openEdit = useCallback((field) => {
    if (field.readonly) return;
    const current = lead[field.apiKey] || '';
    setEditingField(field);

    if (field.type === 'meta_qualified') {
      const v = lead.meta_qualified;
      setDraftValue(v === true ? 'yes' : v === false ? 'no' : 'unset');
      return;
    }

    if (field.type === 'number') {
      const n = lead.site_visit_count;
      setDraftValue(n === 0 || n ? String(n) : '0');
      return;
    }

    setDraftValue(current);

    if (['budget', 'location', 'project', 'source'].includes(field.type)) {
      const options =
        field.type === 'budget'
          ? BUDGET_RANGES
          : field.type === 'location'
            ? locations.length ? locations : mergePicklistWithApi(CANONICAL_LOCATIONS, [])
            : field.type === 'project'
              ? projects.length ? projects : mergePicklistWithApi(CANONICAL_PROJECTS, [])
              : sources.length ? sources : mergePicklistWithApi(CANONICAL_SOURCES, []);
      const next = resolveSelectWithOtherState(current, normalizeOptions(options));
      setSelectMode(next.mode);
      setPresetValue(next.presetValue);
      setOtherText(next.otherText);
    } else {
      setSelectMode('preset');
      setPresetValue('');
      setOtherText('');
    }
  }, [lead, locations, projects, sources]);

  const closeEdit = () => {
    setEditingField(null);
    setDraftValue('');
    setSelectMode('preset');
    setPresetValue('');
    setOtherText('');
  };

  const aiSuggestion = editingField ? getAiValue(lead, editingField.aiKey) : null;
  const crmValue = editingField ? (lead[editingField.apiKey] || '') : '';
  const showAiSuggestion = aiSuggestion && aiSuggestion !== crmValue;

  const resolveSaveValue = () => {
    if (editingField && ['budget', 'location', 'project', 'source'].includes(editingField.type)) {
      const value = resolveSelectWithOtherValue(selectMode, presetValue, otherText);
      return value || null;
    }
    if (editingField?.type === 'meta_qualified') {
      if (draftValue === 'yes') return true;
      if (draftValue === 'no') return false;
      return null;
    }
    if (editingField?.type === 'number') {
      const n = parseInt(draftValue, 10);
      if (!Number.isFinite(n) || n < 0) return null;
      return n;
    }
    return (draftValue || '').trim() || null;
  };

  const handleSave = async (valueOverride) => {
    if (!editingField) return;
    const value = valueOverride !== undefined ? valueOverride : resolveSaveValue();
    setSaving(true);
    try {
      await leadsAPI.update(leadId, { [editingField.apiKey]: value });
      toast.success(`${editingField.label} updated`);
      closeEdit();
      await onLeadUpdated?.();
    } catch (error) {
      toast.error(error.response?.data?.detail || `Failed to update ${editingField.label.toLowerCase()}`);
    } finally {
      setSaving(false);
    }
  };

  const renderEditor = () => {
    if (!editingField) return null;

    switch (editingField.type) {
      case 'budget':
        return (
          <NativeSelectWithOther
            optionNames={BUDGET_RANGES}
            mode={selectMode}
            presetValue={presetValue}
            otherText={otherText}
            onModeChange={setSelectMode}
            onPresetChange={setPresetValue}
            onOtherTextChange={setOtherText}
            placeholder="Select budget range"
            otherPlaceholder="e.g. 4 cr"
          />
        );
      case 'location':
        return (
          <NativeSelectWithOther
            optionNames={picklistNames(locations)}
            mode={selectMode}
            presetValue={presetValue}
            otherText={otherText}
            onModeChange={setSelectMode}
            onPresetChange={setPresetValue}
            onOtherTextChange={setOtherText}
            placeholder={loadingOptions ? 'Loading locations…' : 'Select location'}
            otherPlaceholder="Enter location"
            disabled={loadingOptions}
          />
        );
      case 'project':
        return (
          <NativeSelectWithOther
            optionNames={picklistNames(projects)}
            mode={selectMode}
            presetValue={presetValue}
            otherText={otherText}
            onModeChange={setSelectMode}
            onPresetChange={setPresetValue}
            onOtherTextChange={setOtherText}
            placeholder={loadingOptions ? 'Loading projects…' : 'Select project'}
            otherPlaceholder="Enter project name"
            disabled={loadingOptions}
          />
        );
      case 'source':
        return (
          <NativeSelectWithOther
            optionNames={picklistNames(sources.length ? sources : mergePicklistWithApi(CANONICAL_SOURCES, []))}
            mode={selectMode}
            presetValue={presetValue}
            otherText={otherText}
            onModeChange={setSelectMode}
            onPresetChange={setPresetValue}
            onOtherTextChange={setOtherText}
            placeholder={loadingOptions ? 'Loading sources…' : 'Select source'}
            otherPlaceholder="Enter source"
            disabled={loadingOptions}
          />
        );
      case 'meta_qualified':
        return (
          <select
            value={draftValue}
            onChange={(e) => setDraftValue(e.target.value)}
            className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm"
          >
            <option value="unset">Not set</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        );
      case 'number':
        return (
          <Input
            type="number"
            min={0}
            step={1}
            value={draftValue}
            onChange={(e) => setDraftValue(e.target.value)}
            placeholder="0"
            className="bg-black/50 border-white/10 text-white"
          />
        );
      case 'purpose':
        return (
          <select
            value={draftValue}
            onChange={(e) => setDraftValue(e.target.value)}
            className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm"
          >
            <option value="">Select purpose</option>
            {PURPOSE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        );
      default:
        return (
          <Input
            value={draftValue}
            onChange={(e) => setDraftValue(e.target.value)}
            placeholder={`Enter ${editingField.label.toLowerCase()}`}
            className="bg-black/50 border-white/10 text-white"
          />
        );
    }
  };

  const stickyTopClass = stickySummaryVisible
    ? 'top-[calc(3rem+var(--header-height-compact))]'
    : 'top-12';

  const collapsedPreview = useMemo(() => {
    const parts = [
      lead?.project,
      lead?.budget,
      lead?.configuration,
      lead?.location,
    ].filter((v) => v && v !== 'Not specified');
    return parts.slice(0, 3).join(' · ');
  }, [lead]);

  const isCollapsed = overviewOpen !== 'overview';

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className={[
          'glass-card rounded-lg p-3 lg:p-4',
          sticky ? `lead-overview-sticky sticky ${stickyTopClass}` : '',
        ].filter(Boolean).join(' ')}
        data-testid="data-dna-grid"
      >
        <Accordion
          type="single"
          collapsible
          value={overviewOpen}
          onValueChange={setOverviewOpen}
        >
          <AccordionItem value="overview" className="border-0">
            <AccordionTrigger
              className="hover:no-underline py-0 gap-2"
              data-testid="lead-overview-toggle"
            >
              <div className="flex flex-1 items-center justify-between gap-2 min-w-0 text-left">
                <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2 min-w-0 flex-1">
                  <div className="flex items-center gap-2 min-w-0 flex-wrap">
                    <span className="text-base font-semibold text-white">Lead Overview</span>
                    <span className="lead-overview-index text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded">
                      {FIELD_CONFIG.length} fields
                    </span>
                    <CrmBadge
                      chip
                      variant="gold"
                      className="font-mono shrink-0"
                      data-testid="lead-overview-number"
                      title={leadId}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                    >
                      #{formatLeadNumber(leadId)}
                    </CrmBadge>
                  </div>
                  {isCollapsed && collapsedPreview && (
                    <p
                      className="text-[#A1A1AA] text-xs truncate sm:max-w-[50%]"
                      data-testid="lead-overview-collapsed-preview"
                    >
                      {collapsedPreview}
                    </p>
                  )}
                </div>
              </div>
            </AccordionTrigger>
            <AccordionContent className="pt-2">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {FIELD_CONFIG.map((field, idx) => (
                  <DataDnaCard key={field.id} field={field} lead={lead} onEdit={openEdit} index={idx + 1} />
                ))}
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </motion.div>

      <Dialog open={!!editingField} onOpenChange={(open) => !open && closeEdit()}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl">
              Edit {editingField?.label}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {renderEditor()}
            {showAiSuggestion && (
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg bg-[#C5A059]/10 border border-[#C5A059]/20">
                <p className="text-[#A1A1AA] text-sm flex items-center gap-1.5">
                  <Sparkles size={14} className="text-[#C5A059] shrink-0" />
                  AI suggestion: <span className="text-white">{aiSuggestion}</span>
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  className="border-[#C5A059]/40 text-[#C5A059] hover:bg-[#C5A059]/10 shrink-0"
                  onClick={() => handleSave(aiSuggestion)}
                  disabled={saving}
                >
                  Use AI value
                </Button>
              </div>
            )}
            <div className="flex gap-3">
              <Button
                variant="outline"
                onClick={closeEdit}
                className="flex-1 border-white/10 text-white hover:bg-white/5"
                disabled={saving}
              >
                Cancel
              </Button>
              <Button
                onClick={() => handleSave()}
                disabled={saving}
                className="flex-1 bg-[#C5A059] text-black hover:bg-[#E5C079] disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
