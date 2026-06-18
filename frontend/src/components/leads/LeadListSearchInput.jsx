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
    <form onSubmit={handleSubmit} className="flex-1">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[#52525B]" size={18} />
        <Input
          value={local}
          onChange={(e) => setLocal(e.target.value)}
          placeholder="Search by name, phone, work phone, source, email..."
          className="pl-10 bg-black/50 border-white/10 text-white placeholder:text-[#52525B] h-11"
          data-testid="search-input"
        />
      </div>
    </form>
  );
});
