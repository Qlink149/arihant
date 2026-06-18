import React, { useMemo, useState } from 'react';
import { Calendar, ChevronDown } from 'lucide-react';
import { Button } from '../ui/button';
import { Calendar as CalendarUI } from '../ui/calendar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import {
  QUARTER_OPTIONS,
  addDays,
  emptyDatePeriod,
  formatLocalDate,
  getSalesPeriodLabel,
  isDatePeriodActive,
  parseYmd,
} from '../../utils/salesPeriodFilter';
import { addIstDays, formatIstYmd, istYmdToDate } from '../../utils/datetime';

const CALENDAR_CLASS_NAMES = {
  months: 'flex flex-col',
  month: 'space-y-3',
  caption: 'flex justify-center pt-1 relative items-center text-white',
  caption_label: 'text-sm font-medium text-white',
  nav: 'space-x-1 flex items-center',
  nav_button: 'h-7 w-7 bg-transparent border border-white/10 text-white hover:bg-white/10 p-0 inline-flex items-center justify-center rounded-md',
  nav_button_previous: 'absolute left-1',
  nav_button_next: 'absolute right-1',
  table: 'w-full border-collapse',
  head_row: 'flex',
  head_cell: 'text-[#A1A1AA] rounded-md w-8 font-normal text-[0.75rem]',
  row: 'flex w-full mt-1',
  cell: 'relative p-0 text-center text-sm focus-within:relative focus-within:z-20',
  day: 'h-8 w-8 p-0 font-normal text-white hover:bg-[#C5A059]/20 rounded-md',
  day_selected: 'bg-[#C5A059] text-black hover:bg-[#C5A059] hover:text-black rounded-md',
  day_today: 'bg-white/10 text-white rounded-md',
  day_outside: 'text-[#52525B] opacity-50',
  day_disabled: 'text-[#52525B] opacity-30',
  day_range_middle: 'bg-[#C5A059]/20 text-white rounded-none',
  day_range_start: 'bg-[#C5A059] text-black rounded-l-md rounded-r-none',
  day_range_end: 'bg-[#C5A059] text-black rounded-r-md rounded-l-none',
  day_hidden: 'invisible',
};

export function SalesPeriodFilters({
  quarter = 'all',
  onQuarterChange,
  datePeriod = emptyDatePeriod(),
  onDatePeriodChange,
}) {
  const [dateMenuMode, setDateMenuMode] = useState('presets');
  const [dateDropdownOpen, setDateDropdownOpen] = useState(false);
  const [customDateRange, setCustomDateRange] = useState(() => {
    if (datePeriod.created_from && datePeriod.created_to && datePeriod.created_from !== datePeriod.created_to) {
      return { from: parseYmd(datePeriod.created_from), to: parseYmd(datePeriod.created_to) };
    }
    return null;
  });
  const [singleDate, setSingleDate] = useState(() => {
    if (
      datePeriod.created_from
      && datePeriod.created_to
      && datePeriod.created_from === datePeriod.created_to
      && !datePeriod.days
    ) {
      return parseYmd(datePeriod.created_from);
    }
    return undefined;
  });

  const quarterLabel = useMemo(
    () => QUARTER_OPTIONS.find((o) => o.value === quarter)?.label || 'Quarter',
    [quarter]
  );

  const dateLabel = useMemo(
    () => getSalesPeriodLabel({ quarter: 'all', datePeriod }),
    [datePeriod]
  );

  const dateActive = quarter === 'all' && isDatePeriodActive(datePeriod);

  const handleQuarterChange = (value) => {
    onQuarterChange?.(value);
    if (value !== 'all') {
      onDatePeriodChange?.(emptyDatePeriod());
      setCustomDateRange(null);
      setSingleDate(undefined);
    }
  };

  const applyDatePreset = (preset) => {
    const clear = emptyDatePeriod();

    setDateMenuMode('presets');

    if (preset === 'all') {
      setCustomDateRange(null);
      setSingleDate(undefined);
      onQuarterChange?.('all');
      onDatePeriodChange?.(clear);
      setDateDropdownOpen(false);
      return;
    }

    onQuarterChange?.('all');
    setCustomDateRange(null);

    if (['7', '30', '60', '90'].includes(preset)) {
      setSingleDate(undefined);
      onDatePeriodChange?.({ ...clear, days: preset });
      setDateDropdownOpen(false);
      return;
    }

    let ymd = formatIstYmd();
    if (preset === 'yesterday') ymd = addIstDays(-1);
    if (preset === 'day_before') ymd = addIstDays(-2);
    const target = istYmdToDate(ymd);
    setSingleDate(target || undefined);
    onDatePeriodChange?.({ ...clear, created_from: ymd, created_to: ymd });
    setDateDropdownOpen(false);
  };

  const handleCustomRangeSelect = (range) => {
    onQuarterChange?.('all');
    setCustomDateRange(range);
    if (!range?.from) return;

    const from = formatLocalDate(range.from);
    const to = range.to ? formatLocalDate(range.to) : from;
    setSingleDate(undefined);
    onDatePeriodChange?.({
      days: '',
      created_from: from,
      created_to: to,
    });

    if (range.to) {
      setDateMenuMode('presets');
      setDateDropdownOpen(false);
    }
  };

  const handleSingleDateSelect = (date) => {
    if (!date) return;
    onQuarterChange?.('all');
    setSingleDate(date);
    const ymd = formatLocalDate(date);
    setCustomDateRange(null);
    onDatePeriodChange?.({
      days: '',
      created_from: ymd,
      created_to: ymd,
    });
    setDateMenuMode('presets');
    setDateDropdownOpen(false);
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 h-9 ${
              quarter !== 'all' ? 'border-[#C5A059] text-[#C5A059]' : ''
            }`}
            data-testid="sales-quarter-filter"
          >
            {quarterLabel}
            <ChevronDown size={14} className="ml-2" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="bg-[#1A1A1A] border-white/10 max-h-72 overflow-y-auto" align="start">
          <DropdownMenuLabel className="text-[#A1A1AA]">Quarter</DropdownMenuLabel>
          <DropdownMenuSeparator className="bg-white/10" />
          {QUARTER_OPTIONS.map((opt) => (
            <DropdownMenuItem
              key={opt.value}
              onClick={() => handleQuarterChange(opt.value)}
              className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
            >
              {opt.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu
        open={dateDropdownOpen}
        onOpenChange={(open) => {
          setDateDropdownOpen(open);
          if (!open) setDateMenuMode('presets');
        }}
      >
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 h-9 ${
              dateActive ? 'border-[#C5A059] text-[#C5A059]' : ''
            }`}
            data-testid="sales-date-filter"
          >
            <Calendar size={14} className="mr-2" />
            {dateActive ? dateLabel : 'Date'}
            <ChevronDown size={14} className="ml-2" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          className="bg-[#1A1A1A] border-white/10"
          align="start"
          data-testid="sales-date-filter-menu"
        >
          {dateMenuMode === 'presets' ? (
            <>
              <DropdownMenuLabel className="text-[#A1A1AA]">Created date</DropdownMenuLabel>
              <DropdownMenuSeparator className="bg-white/10" />
              <DropdownMenuItem
                onClick={() => applyDatePreset('today')}
                className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
              >
                Today (IST)
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => applyDatePreset('yesterday')}
                className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
              >
                Yesterday (IST)
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => applyDatePreset('day_before')}
                className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
              >
                Day before yesterday (IST)
              </DropdownMenuItem>
              <DropdownMenuSeparator className="bg-white/10" />
              {[7, 30, 60, 90].map((n) => (
                <DropdownMenuItem
                  key={n}
                  onClick={() => applyDatePreset(String(n))}
                  className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                >
                  Last {n} days
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator className="bg-white/10" />
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  setDateMenuMode('single');
                }}
                className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                data-testid="sales-date-pick-single"
              >
                Pick a date
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  setDateMenuMode('custom');
                }}
                className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                data-testid="sales-date-custom-range"
              >
                Custom range
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => applyDatePreset('all')}
                className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
              >
                All time
              </DropdownMenuItem>
            </>
          ) : null}

          {dateMenuMode === 'single' ? (
            <>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  setDateMenuMode('presets');
                }}
                className="text-[#A1A1AA] hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
              >
                ← Back to presets
              </DropdownMenuItem>
              <DropdownMenuSeparator className="bg-white/10" />
              <DropdownMenuItem
                className="p-0 focus:bg-transparent cursor-default"
                onSelect={(e) => e.preventDefault()}
                onPointerDown={(e) => e.preventDefault()}
              >
                <CalendarUI
                  mode="single"
                  selected={singleDate}
                  onSelect={handleSingleDateSelect}
                  classNames={CALENDAR_CLASS_NAMES}
                  className="p-3 bg-[#1A1A1A] text-white"
                  data-testid="sales-date-single-calendar"
                />
              </DropdownMenuItem>
            </>
          ) : null}

          {dateMenuMode === 'custom' ? (
            <>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  setDateMenuMode('presets');
                }}
                className="text-[#A1A1AA] hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
              >
                ← Back to presets
              </DropdownMenuItem>
              <DropdownMenuSeparator className="bg-white/10" />
              <DropdownMenuItem
                className="p-0 focus:bg-transparent cursor-default"
                onSelect={(e) => e.preventDefault()}
                onPointerDown={(e) => e.preventDefault()}
              >
                <CalendarUI
                  mode="range"
                  selected={customDateRange}
                  onSelect={handleCustomRangeSelect}
                  classNames={CALENDAR_CLASS_NAMES}
                  className="p-3 bg-[#1A1A1A] text-white"
                  numberOfMonths={1}
                  data-testid="sales-date-range-calendar"
                />
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export default SalesPeriodFilters;
