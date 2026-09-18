/** Projects with WhatsApp pricing templates (mirrors backend PROJECT_PRICING_MAP). */

export const WHATSAPP_PRICING_PROJECTS = [
  {
    key: 'melange',
    label: 'Mélange',
    pricePreview: '₹12,800/sq.ft. (basic price) + other applicable charges',
    priced: true,
  },
  {
    key: 'reserve-16',
    label: 'Reserve 16',
    pricePreview: '₹3,500/sq.ft. (basic price) + other applicable charges',
    priced: true,
  },
  {
    key: 'vivriti',
    label: 'Vivriti',
    pricePreview: '₹13,000/sq.ft. (basic price) + other applicable charges',
    priced: true,
  },
  {
    key: 'krsna',
    label: 'Krsna',
    pricePreview: null,
    priced: false,
  },
];

const PROJECT_KEY_TOKENS = [
  ['mélange', 'melange'],
  ['melange', 'melange'],
  ['reserve-16', 'reserve-16'],
  ['reserve 16', 'reserve-16'],
  ['reserve16', 'reserve-16'],
  ['vivriti', 'vivriti'],
  ['krishna', 'krsna'],
  ['krsna', 'krsna'],
  ['abhiramapuram', 'krsna'],
  ['abiramapuram', 'krsna'],
];

const KNOWN_KEYS = new Set(WHATSAPP_PRICING_PROJECTS.map((p) => p.key));

/** Map a display name or slug to a canonical pricing project key. */
export function resolvePricingProjectKey(nameOrKey) {
  const raw = String(nameOrKey || '').trim();
  if (!raw) return '';
  const lower = raw.toLowerCase();
  if (KNOWN_KEYS.has(lower)) return lower;
  let bestPos = -1;
  let bestKey = '';
  for (const [token, key] of PROJECT_KEY_TOKENS) {
    const pos = lower.indexOf(token);
    if (pos >= 0 && (bestPos < 0 || pos < bestPos)) {
      bestPos = pos;
      bestKey = key;
    }
  }
  return bestKey;
}

export function getPricingProjectByKey(key) {
  return WHATSAPP_PRICING_PROJECTS.find((p) => p.key === key) || null;
}
