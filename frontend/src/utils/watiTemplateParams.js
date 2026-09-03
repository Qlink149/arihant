/**
 * Parse WATI template variables for pre-send editing.
 * Prefer custom_params [{name, value}]; else {{1}} / {{2}} in body/hsm.
 */

export function templateBodyText(template) {
  if (!template || typeof template !== 'object') return '';
  return (
    template.body
    || template.body_original
    || template.hsm
    || template.hsm_original
    || ''
  );
}

/**
 * @param {object} template
 * @param {{ name?: string, project?: string }} defaults
 * @returns {{ index: number, name: string, label: string, defaultValue: string }[]}
 */
export function parseTemplateVariables(template, defaults = {}) {
  const nameDefault = defaults.name != null ? String(defaults.name) : '';
  const projectDefault = defaults.project != null ? String(defaults.project) : '';

  const custom = Array.isArray(template?.custom_params) ? template.custom_params : [];
  if (custom.length > 0) {
    return custom.map((p, i) => {
      const pname = String(p?.name ?? `var${i + 1}`).trim() || `var${i + 1}`;
      const low = pname.toLowerCase();
      let defaultValue = p?.value != null ? String(p.value) : '';
      if (!defaultValue) {
        if (low.includes('name') || low === '1') defaultValue = nameDefault;
        else if (low.includes('project') || low === '2') defaultValue = projectDefault;
      }
      return {
        index: i,
        name: pname,
        label: pname.replace(/_/g, ' '),
        defaultValue,
      };
    });
  }

  const body = templateBodyText(template);
  const matches = [...body.matchAll(/\{\{(\d+)\}\}/g)];
  const seen = new Set();
  const vars = [];
  for (const m of matches) {
    const n = parseInt(m[1], 10);
    if (!Number.isFinite(n) || seen.has(n)) continue;
    seen.add(n);
    const pname = String(n);
    let defaultValue = '';
    if (n === 1) defaultValue = nameDefault;
    else if (n === 2) defaultValue = projectDefault;
    vars.push({
      index: n - 1,
      name: pname,
      label: `Variable ${n}`,
      defaultValue,
    });
  }
  vars.sort((a, b) => a.index - b.index);
  if (vars.length > 0) return vars;

  // No custom_params and no {{n}} placeholders — one editable fallback.
  return [
    {
      index: 0,
      name: 'name',
      label: 'Value',
      defaultValue: nameDefault || projectDefault || '',
    },
  ];
}

/**
 * Build [{name, value}] for WATI send from edited form state.
 */
export function buildTemplateParameters(variables, valuesByName) {
  if (!variables?.length) return [];
  return variables.map((v) => ({
    name: v.name,
    value: String(valuesByName?.[v.name] ?? v.defaultValue ?? ''),
  }));
}
