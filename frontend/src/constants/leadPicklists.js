/** Canonical picklists for lead Source, Project, Location, and Budget fields. */

export const BUDGET_RANGES = ['Under 1Cr', '1-2 Cr', '2-5 Cr', '5 Cr+'];

export const CANONICAL_PROJECTS = [
  'ECR - Reserve 16',
  'OMR - Vivriti',
  'Saligramam - Melange',
  'Anna Nagar - Mira',
  'Abhiramapuram - Krsna',
  'NA',
  'MGR Salai - Perungudi',
  'Velachery - Park Street',
  'Others',
  'Hunters Road - Vanya Vilas',
  'Venus Colony - Saraswathi',
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
  'Vihaana',
  'Amara',
  'All projects',
  'Commercial Projects',
  'Commercial - Vayu',
  'Poes Garden - Chirla',
  'ECR - Swarang',
  'Flowers Road - Mehek',
  'Bangalore - Vilaya',
  'Srinagar Colony - Vipassana',
  'Homepage Enquiry',
  'Perambur - Ekanta',
  'Sold Out Enquiry',
  'Chamiers Road - Project',
  'Guindy',
  'Thoraipakkam',
  'Vista',
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
  'Facebook',
  'Incoming call',
  'Instagram',
  'Direct Walk-in',
  'Existing Customer',
  'BTL',
  'Google',
  'Website',
  'Email campaign',
  'Management Referral',
  'Referral',
  'Site Branding',
  'Outdoor Hoarding',
  'Newspaper',
  'Mcube Inbound',
  'Whatsapp',
  'Wati Campaign',
  'Genie',
  'Aurum Analytica',
  'Magic Bricks',
  'Chennai Properties',
  'Housing.com',
  'Roof and Floor',
  'Credai Fairpro 2026',
  'Credai Fairpro 2025',
  'Property fair 2024',
  'Channel Partner',
  'Others',
  'Testing',
  // Legacy / not-yet-remapped picklist entries kept for backward compatibility.
  '19 estates',
  '99acres',
  'cold calling',
  'commonfloor',
  'corporate activity',
  'data migration',
  'economic_times',
  'employee referral',
  'etconnect',
  'event / exhibition',
  'gantry',
  'justdial',
  'landingpage',
  'leaflet',
  'linkedin',
  'magicbricks',
  'mygate',
  'offline activity',
  'old digital leads',
  'organic',
  'outdoor-mobile van',
  'portal',
  'print',
  'property_portal',
  'propertyfinder',
  'propertywala',
  'propstory',
  'prospect referral',
  'quora ads',
  'radio',
  'realatte',
  'realty acres',
  'self generated',
  'society marketing',
  'taboola',
  'tele calling',
  'times_of_india',
  'twitter',
  'voice calls',
  'youtube',
];

// Channel Partner submission-form dropdown (cp-leads-r16 / cp-leads-melange / cp-leads-mira).
// Keep in sync with backend/crm/constants/lead_picklists.py CANONICAL_CHANNEL_PARTNERS.
export const CANONICAL_CHANNEL_PARTNERS = [
  'Home Konnect',
  'Propmart',
  'PropLeaf',
  'Kaaviya Homes',
  'Nobroker',
  'Chennai Gated Community',
  'Southzone Realty',
  'Medsea Properties',
  'Proptiger',
  'Thara properties',
  'JLL',
  'Prop Smile',
  'Reliable Consultancy',
  'C4 Realty',
  'Proffiz',
  'Estates61',
  'Ground7Realty',
  'Options Realtors & Tenancy management',
  'SRS Properties',
  'Elite Realtors',
  'Property Book',
  'Rare property',
  'Meadows Realty',
  'Zubair Realty',
  'Tora',
  'Propjoy',
  'Housepecker',
  'Hanu Reddy',
  'Gopal Realty',
  'Right Choice',
  'Avishtra',
  '24K',
  '3pin Realty',
  'F&P Homes',
  'Connection Point',
  'Property Pistol',
  '5star Realestate',
  'Prop Crest',
  'Individual',
  'HomeAvenue Realty',
  'Rentostay',
  'Others',
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
