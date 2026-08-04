import React, { memo, useMemo, useCallback } from 'react';
import { ChevronDown } from 'lucide-react';
import { Button } from '../ui/button';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import { formatMultiLabel } from '../../utils/leadFilters';

export const MultiSelectFilterDropdown = memo(function MultiSelectFilterDropdown({
  label,
  icon: Icon,
  options = [],
  selected = [],
  onChange,
  loading = false,
  testId,
  className = '',
}) {
  const [open, setOpen] = React.useState(false);
  const isActive = Array.isArray(selected) && selected.length > 0;
  const displayLabel = formatMultiLabel(selected, label);

  const normalizedOptions = useMemo(
    () => options.map((opt) => (typeof opt === 'string' ? { name: opt, count: null } : opt)),
    [options],
  );

  const toggle = useCallback(
    (value, checked) => {
      const list = Array.isArray(selected) ? [...selected] : [];
      if (checked) {
        if (!list.includes(value)) list.push(value);
      } else {
        const idx = list.indexOf(value);
        if (idx >= 0) list.splice(idx, 1);
      }
      onChange(list);
    },
    [selected, onChange],
  );

  const handleClear = useCallback(() => onChange([]), [onChange]);
  const handleDone = useCallback(() => setOpen(false), []);

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className={`bg-crm-elevated border-crm-border text-white hover:bg-white/5 ${
            isActive ? 'border-[#C5A059] text-[#C5A059]' : ''
          } ${className}`}
          data-testid={testId}
        >
          {Icon ? <Icon size={14} className="mr-2" /> : null}
          {displayLabel}
          <ChevronDown size={14} className="ml-2" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        className="bg-crm-elevated border-crm-border max-h-72 overflow-y-auto"
        align="start"
        onCloseAutoFocus={(e) => e.preventDefault()}
      >
        <DropdownMenuLabel className="text-crm-fg-secondary">{label}</DropdownMenuLabel>
        <DropdownMenuSeparator className="bg-white/10" />
        {loading ? (
          <DropdownMenuItem disabled className="text-crm-fg-muted">
            Loading…
          </DropdownMenuItem>
        ) : normalizedOptions.length === 0 ? (
          <DropdownMenuItem disabled className="text-crm-fg-muted">
            No options
          </DropdownMenuItem>
        ) : (
          normalizedOptions.map((item) => (
            <DropdownMenuCheckboxItem
              key={item.name}
              checked={selected.includes(item.name)}
              onCheckedChange={(checked) => toggle(item.name, checked)}
              onSelect={(e) => e.preventDefault()}
              className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
            >
              {item.name}
              {item.count != null ? (
                <span className="ml-2 text-crm-fg-muted text-xs">({item.count})</span>
              ) : null}
            </DropdownMenuCheckboxItem>
          ))
        )}
        <DropdownMenuSeparator className="bg-white/10" />
        <DropdownMenuItem
          onClick={handleClear}
          disabled={!isActive}
          className="text-crm-fg-secondary hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
        >
          Clear all
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={handleDone}
          className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
        >
          Done
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
});
