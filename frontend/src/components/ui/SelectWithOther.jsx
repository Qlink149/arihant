import React, { useEffect, useMemo, useState } from 'react';
import { Input } from './input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './select';
import {
  OTHER_OPTION_VALUE,
  normalizeOptions,
  resolveSelectWithOtherState,
  resolveSelectWithOtherValue,
} from '../../utils/selectWithOther';

export function SelectWithOther({
  value = '',
  onChange,
  onModeChange,
  options = [],
  placeholder = 'Select…',
  otherPlaceholder = 'Enter custom value',
  loading = false,
  disabled = false,
  loadingLabel = 'Loading…',
  className = '',
  otherInputTestId,
}) {
  const optionsKey = useMemo(
    () => normalizeOptions(options).join('\u0001'),
    [options]
  );
  const optionNames = useMemo(() => normalizeOptions(options), [optionsKey]);

  const [mode, setMode] = useState('preset');
  const [presetValue, setPresetValue] = useState('');
  const [otherText, setOtherText] = useState('');

  useEffect(() => {
    const next = resolveSelectWithOtherState(value, optionNames);
    setMode(next.mode);
    setPresetValue(next.presetValue);
    setOtherText(next.otherText);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync local state from value/options only
  }, [value, optionNames]);

  const selectValue = mode === 'other' ? OTHER_OPTION_VALUE : presetValue || '';

  const emitChange = (nextMode, nextPreset, nextOther) => {
    onChange?.(resolveSelectWithOtherValue(nextMode, nextPreset, nextOther));
  };

  const handleSelectChange = (selected) => {
    if (selected === OTHER_OPTION_VALUE) {
      setMode('other');
      setPresetValue('');
      onModeChange?.('other');
      emitChange('other', '', otherText);
      return;
    }
    setMode('preset');
    setPresetValue(selected);
    setOtherText('');
    onModeChange?.('preset');
    emitChange('preset', selected, '');
  };

  const handleOtherTextChange = (text) => {
    setMode('other');
    setOtherText(text);
    onModeChange?.('other');
    emitChange('other', '', text);
  };

  return (
    <div className={`space-y-2 ${className}`}>
      <Select
        value={selectValue || undefined}
        onValueChange={handleSelectChange}
        disabled={disabled || loading}
      >
        <SelectTrigger className="bg-black/50 border-white/10 text-white">
          <SelectValue placeholder={loading ? loadingLabel : placeholder} />
        </SelectTrigger>
        <SelectContent className="bg-[#1A1A1A] border-white/10 max-h-60 overflow-y-auto">
          {loading ? (
            <SelectItem value="__loading" disabled className="text-[#52525B]">
              {loadingLabel}
            </SelectItem>
          ) : (
            <>
              {optionNames.map((name) => (
                <SelectItem
                  key={name}
                  value={name}
                  className="text-white hover:bg-[#C5A059]/10"
                >
                  {name}
                </SelectItem>
              ))}
              <SelectItem
                value={OTHER_OPTION_VALUE}
                className="text-white hover:bg-[#C5A059]/10"
              >
                Other
              </SelectItem>
            </>
          )}
        </SelectContent>
      </Select>
      {mode === 'other' && !loading ? (
        <Input
          value={otherText}
          onChange={(e) => handleOtherTextChange(e.target.value)}
          placeholder={otherPlaceholder}
          className="bg-black/50 border-white/10 text-white"
          disabled={disabled}
          data-testid={otherInputTestId}
        />
      ) : null}
    </div>
  );
}
