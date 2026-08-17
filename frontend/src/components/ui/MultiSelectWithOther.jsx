import React, { memo, useCallback, useMemo, useState } from 'react';
import { ChevronDown, X } from 'lucide-react';
import { Button } from './button';
import { Input } from './input';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './dropdown-menu';
import { formatMultiLabel } from '../../utils/leadFilters';
import { normalizeOptions } from '../../utils/selectWithOther';

export function isMultiSelectWithOtherEmpty(value) {
  return !Array.isArray(value) || value.length === 0;
}

export const MultiSelectWithOther = memo(function MultiSelectWithOther({
  value = [],
  onChange,
  options = [],
  placeholder = 'Select…',
  otherPlaceholder = 'Enter custom value',
  loading = false,
  disabled = false,
  className = '',
  testId,
  otherInputTestId,
}) {
  const [open, setOpen] = useState(false);
  const [otherText, setOtherText] = useState('');
  const selected = Array.isArray(value) ? value : [];
  const optionNames = useMemo(() => normalizeOptions(options), [options]);
  const displayLabel = formatMultiLabel(selected, placeholder);

  const toggle = useCallback(
    (name, checked) => {
      const list = [...selected];
      if (checked) {
        if (!list.includes(name)) list.push(name);
      } else {
        const idx = list.indexOf(name);
        if (idx >= 0) list.splice(idx, 1);
      }
      onChange?.(list);
    },
    [selected, onChange],
  );

  const addOther = useCallback(() => {
    const name = (otherText || '').trim();
    if (!name) return;
    const list = [...selected];
    if (!list.some((item) => String(item).toLowerCase() === name.toLowerCase())) {
      list.push(name);
      onChange?.(list);
    }
    setOtherText('');
  }, [otherText, selected, onChange]);

  const remove = useCallback(
    (name) => {
      onChange?.(selected.filter((item) => item !== name));
    },
    [selected, onChange],
  );

  return (
    <div className={className}>
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            disabled={disabled || loading}
            className="w-full justify-between bg-crm-muted border-crm-border text-white hover:bg-white/5"
            data-testid={testId}
          >
            <span className="truncate">{loading ? 'Loading…' : displayLabel}</span>
            <ChevronDown size={14} className="ml-2 shrink-0" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          className="bg-crm-elevated border-crm-border max-h-72 overflow-y-auto w-[var(--radix-dropdown-menu-trigger-width)] min-w-[16rem]"
          align="start"
          onCloseAutoFocus={(e) => e.preventDefault()}
        >
          <DropdownMenuLabel className="text-crm-fg-secondary">{placeholder}</DropdownMenuLabel>
          <DropdownMenuSeparator className="bg-white/10" />
          {loading ? (
            <DropdownMenuItem disabled className="text-crm-fg-muted">
              Loading…
            </DropdownMenuItem>
          ) : optionNames.length === 0 ? (
            <DropdownMenuItem disabled className="text-crm-fg-muted">
              No options
            </DropdownMenuItem>
          ) : (
            optionNames.map((name) => (
              <DropdownMenuCheckboxItem
                key={name}
                checked={selected.includes(name)}
                onCheckedChange={(checked) => toggle(name, checked)}
                onSelect={(e) => e.preventDefault()}
                className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
              >
                {name}
              </DropdownMenuCheckboxItem>
            ))
          )}
          <DropdownMenuSeparator className="bg-white/10" />
          <div className="px-2 py-2 space-y-2" onClick={(e) => e.stopPropagation()}>
            <Input
              value={otherText}
              onChange={(e) => setOtherText(e.target.value)}
              placeholder={otherPlaceholder}
              className="bg-crm-muted border-crm-border text-crm-fg h-8"
              data-testid={otherInputTestId}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addOther();
                }
              }}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="w-full h-7 text-xs"
              onClick={addOther}
              disabled={!otherText.trim()}
            >
              Add custom
            </Button>
          </div>
        </DropdownMenuContent>
      </DropdownMenu>
      {selected.length > 0 ? (
        <div className="flex flex-wrap gap-1 mt-2">
          {selected.map((name) => (
            <span
              key={name}
              className="inline-flex items-center gap-1 rounded-full bg-white/10 text-crm-fg text-xs px-2 py-0.5"
            >
              {name}
              <button
                type="button"
                aria-label={`Remove ${name}`}
                className="hover:text-[#C5A059]"
                onClick={() => remove(name)}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
});
