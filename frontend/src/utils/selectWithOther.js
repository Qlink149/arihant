export const OTHER_OPTION_VALUE = '__other__';

export const normalizeOptions = (options) => {
  if (!Array.isArray(options)) return [];
  return options
    .map((opt) => {
      if (typeof opt === 'string') return opt.trim();
      if (opt && typeof opt.name === 'string') return opt.name.trim();
      return '';
    })
    .filter(Boolean);
};

export const resolveSelectWithOtherState = (value, optionNames) => {
  const names = normalizeOptions(optionNames);
  const raw = (value || '').trim();

  if (!raw) {
    return { mode: 'preset', presetValue: '', otherText: '' };
  }

  if (names.includes(raw)) {
    return { mode: 'preset', presetValue: raw, otherText: '' };
  }

  return { mode: 'other', presetValue: '', otherText: raw };
};

export const resolveSelectWithOtherValue = (mode, presetValue, otherText) => {
  if (mode === 'other') {
    return (otherText || '').trim();
  }
  return (presetValue || '').trim();
};

export const isOtherModeWithEmptyText = (mode, otherText) =>
  mode === 'other' && !(otherText || '').trim();
