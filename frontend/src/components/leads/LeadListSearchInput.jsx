import React, { memo, useState, useEffect, useCallback } from 'react';
import { Search } from 'lucide-react';
import { Input } from '../ui/input';

export const LeadListSearchInput = memo(function LeadListSearchInput({
  value = '',
  onDebouncedChange,
  onSubmit,
}) {
  const [local, setLocal] = useState(value);

  useEffect(() => {
    setLocal(value);
  }, [value]);

  useEffect(() => {
    const delay = local.trim() ? 400 : 0;
    const t = setTimeout(() => onDebouncedChange(local.trim()), delay);
    return () => clearTimeout(t);
  }, [local, onDebouncedChange]);

  const handleSubmit = useCallback(
    (e) => {
      e.preventDefault();
      onSubmit?.();
    },
    [onSubmit],
  );

  return (
    <form onSubmit={handleSubmit} className="w-full min-w-0">
      <div className="relative w-full">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-crm-fg-muted" size={18} />
        <Input
          value={local}
          onChange={(e) => setLocal(e.target.value)}
          placeholder="Search by name, phone, work phone, source, email..."
          className="w-full pl-10 bg-crm-muted border-crm-border text-white placeholder:text-crm-fg-muted h-11"
          data-testid="search-input"
        />
      </div>
    </form>
  );
});
