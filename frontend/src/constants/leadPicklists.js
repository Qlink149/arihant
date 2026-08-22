/** Canonical picklists for lead Source, Project, Location, and Budget fields. */

export const BUDGET_RANGES = ['Under 1Cr', '1-2 Cr', '2-5 Cr', '5 Cr+'];

export const CANONICAL_PROJECTS = [
  'ECR - Reserve 16',
  'OMR - Vivriti',
  'Saligramam Melange',
  'Anna Nagar - Mira',
  'Abhiramapuram - Krishna',
  'NA',
  'MGR Salai - Perungudi',
  'Velachery upcoming',
  'Others',
  'Hunters Road - Vanya Vilas',
  'Saraswathi',
  'Sri Nivas',
  'Rohini',
  'Villa Viviana Plots',
  'Tiara',
  'Besant Nagar',
  'Esta',
  'Greenwood City',
  'Sri Niketan',
  'Vinyasa',
  'Harrington Road - Aurelia',
  'Greenwood Commercial',
  'Vihaana',
  'Amara',
  'All projects',
  'Commercial Projects',
  'Commercial - Vayu',
  'Poes Garden - Chirla',
  'ECR - Swarang',
  'Flowers Road - Kilpauk',
  'Bangalore - Vilaya',
  'Srinagar Colony - Vipassana',
  'Homepage Enquiry',
  'Perambur - Ekanta',
  'Venus Colony - Saraswathi',
  'Sold Out Enquiry',
  'Chamiers Road - Project',
  'Guindy',
  'Thoraipakkam',
];

export const CANONICAL_LOCATIONS = [
  'Adyar',
  'Abiramapuram',
  'Alwarpet',
  'Ambattur',
  'Aminjikarai',
  'Anna Nagar',
  'Ashok Nagar',
  'Ayanavaram',
  'Besant Nagar',
  'Boat Club Road',
  'Cathedral Road',
  'Cenotaph Road',
  'Chetpet',
  'Chromepet',
  'Egmore',
  'Ennore',
  'Gopalapuram',
  'Guindy',
  'Harrington Road',
  'Injambakkam',
  'Kelambakkam',
  'Kilpauk',
  'KK Nagar',
  'Korattur',
  'Kotturpuram',
  'Kovalam',
  'Madhavaram',
  'Madipakkam',
  'Mahabalipuram',
  'Mandaveli',
  'Medavakkam',
  'Mogappair',
  'Muttukadu',
  'Mylapore',
  'Nanganallur',
  'Navalur',
  'Neelankarai',
  'Nolambur',
  'Nungambakkam',
  'Others',
  'Padur',
  'Palavakkam',
  'Pallavaram',
  'Pallikaranai',
  'Pattipulam',
  'Perambur',
  'Perungudi',
  'Poes Garden',
  'Porur',
  'Purasawalkam',
  'R.A. Puram',
  'Red Hills',
  'Royapettah',
  'Saligramam',
  'Selaiyur',
  'Shenoy Nagar',
  'Sholinganallur',
  'Siruseri',
  'T. Nagar',
  'Tambaram',
  'Teynampet',
  'Thiruvanmiyur',
  'Thoraipakkam',
  'Uthandi',
  'Vadapalani',
  'Valasaravakkam',
  'Velachery',
  'Vepery',
  'Virugambakkam',
];

export const CANONICAL_SOURCES = [
  '19 estates',
  '99acres',
  'adwords',
  'aurum analytica',
  'brochure',
  'btl',
  'channel partner',
  'chatbot',
  'chennai_properties',
  'cold calling',
  'commonfloor',
  'corporate activity',
  'credai expo',
  'data migration',
  'digital',
  'direct',
  'direct walk-in',
  'economic_times',
  'email',
  'employee referral',
  'etconnect',
  'event / exhibition',
  'expo',
  'facebook_ad',
  'gantry',
  'google ads',
  'hoarding',
  'housing',
  'instagram',
  'justdial',
  'landingpage',
  'leaflet',
  'linkedin',
  'magicbricks',
  'management referral',
  'mcube',
  'mygate',
  'newspaper',
  'nobroker',
  'offline activity',
  'old digital leads',
  'organic',
  'outdoor',
  'outdoor-mobile van',
  'portal',
  'print',
  'property fair',
  'property_portal',
  'propertyfinder',
  'propertywala',
  'propstory',
  'prospect referral',
  'quora ads',
  'radio',
  'realatte',
  'realty acres',
  'referral',
  'roofandfloor',
  'self generated',
  'signage',
  'sitebranding',
  'socialmedia',
  'society marketing',
  'taboola',
  'tele calling',
  'testing',
  'times_of_india',
  'twitter',
  'voice calls',
  'website',
  'whatsapp',
  'youtube',
];

const normKey = (value) => String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');

/** Merge canonical names with API filter-options rows (canonical first). */
export const mergePicklistWithApi = (canonical, apiRows = []) => {
  const counts = new Map();
  const displayByKey = new Map();
  for (const row of apiRows) {
    const name = String(row?.name || '').trim();
    if (!name) continue;
    const key = normKey(name);
    counts.set(key, (counts.get(key) || 0) + Number(row?.count || 0));
    if (!displayByKey.has(key)) displayByKey.set(key, name);
  }

  const merged = [];
  const seen = new Set();
  for (const name of canonical) {
    const key = normKey(name);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push({ name, count: counts.get(key) || 0 });
  }

  const extras = [];
  for (const [key, name] of displayByKey.entries()) {
    if (seen.has(key)) continue;
    extras.push({ name, count: counts.get(key) || 0 });
  }
  extras.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  return [...merged, ...extras];
};

/** Option name strings for SelectWithOther / MultiSelect. */
export const picklistNames = (rows) =>
  (Array.isArray(rows) ? rows : []).map((r) => (typeof r === 'string' ? r : r?.name)).filter(Boolean);
