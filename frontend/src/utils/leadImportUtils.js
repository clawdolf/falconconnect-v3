/**
 * leadImportUtils.js — FalconConnect v3
 *
 * Shared lead import utilities: constants, column mapping, vendor detection, lead building.
 * Used by LeadImport.jsx for multi-CSV batch import.
 *
 * ⚠️  COLUMN_ALIASES are production-tested (57 patterns verified). Do not modify without re-testing.
 * ⚠️  buildLeads() logic (full_name splitting, phone fallback, boolean normalization, 2-digit birth year)
 *     is verified correct. Do not change normalization behavior.
 */


// ═══════════════════════════════════════════════
// SECTION 1 — Vendor & Tier Constants
// ═══════════════════════════════════════════════

export const VENDOR_TIERS = {
  'HOFLeads':      ['Diamond', 'Gold', 'Silver'],
  'Proven Leads':  ['N/A'],
  'Aria Leads':    ['Gold', 'Silver', 'N/A'],
  'MilMo':         ['Gold', 'Silver', 'N/A'],
  'Cheryl':        ['T1', 'T2', 'T3', 'T4', 'T5'],
}

export const NEEDS_LEAD_AGE = {
  'HOFLeads': false,
  'Proven Leads': true,
  'Aria Leads': true,
  'MilMo': true,
  'Cheryl': true,
}

export const VENDOR_AGE_BUCKETS = {
  'HOFLeads':      [],
  'Proven Leads':  ['3M', '6M', '7\u201312M', '13\u201324M', '25\u201336M', '37\u201348M', '49\u201360M', '60+M'],
  'Aria Leads':    ['7\u201312M', '13\u201324M', '25\u201336M', '37\u201348M', '49\u201360M', '60+M'],
  'MilMo':         ['7\u201312M', '13\u201324M', '25\u201336M', '37\u201348M', '49\u201360M', '60+M'],
  'Cheryl':        ['T1', 'T2', 'T3', 'T4', 'T5'],
}

/** Legacy fallback — kept for any code that imported LEAD_AGE_BUCKETS directly */
export const LEAD_AGE_BUCKETS = ['7\u201312M', '13\u201324M', '25\u201336M', '37\u201348M', '49\u201360M', '60+M']


// ═══════════════════════════════════════════════
// SECTION 2 — Lead Types & Vendors
// ═══════════════════════════════════════════════

export const LEAD_TYPES = ['Mortgage Protection', 'Final Expense', 'Annuity', 'IUL']

export const LEAD_VENDORS = Object.keys(VENDOR_TIERS)


// ═══════════════════════════════════════════════
// SECTION 3 — Lead Field Definitions (for mapping dropdowns)
// ═══════════════════════════════════════════════

export const LEAD_FIELDS = [
  // Names
  { value: 'full_name', label: 'Full Name (split into first + last)' },
  { value: 'first_name', label: 'First Name' },
  { value: 'last_name', label: 'Last Name' },

  // Phone
  { value: 'phone', label: 'Phone' },
  { value: 'home_phone', label: 'Home Phone' },
  { value: 'mobile_phone', label: 'Mobile Phone' },
  { value: 'spouse_phone', label: 'Spouse Phone' },

  // Contact
  { value: 'email', label: 'Email' },
  { value: 'address', label: 'Address' },
  { value: 'city', label: 'City' },
  { value: 'county', label: 'County' },
  { value: 'state', label: 'State' },
  { value: 'zip_code', label: 'ZIP Code' },

  // Demographics
  { value: 'birth_year', label: 'Birth Year' },
  { value: 'dob', label: 'DOB (Full Date)' },
  { value: 'gender', label: 'Gender' },

  // Lead metadata
  { value: 'lead_source', label: 'Lead Source' },
  { value: 'lead_type', label: 'Lead Type' },
  { value: 'lead_age_bucket', label: 'Lead Age Bucket' },
  { value: 'lpd', label: 'Lead Purchase Date (LPD)' },

  // Financial
  { value: 'lender', label: 'Lender' },
  { value: 'loan_amount', label: 'Loan Amount' },
  { value: 'mail_date', label: 'Mail Date' },

  // Notes & flags
  { value: 'notes', label: 'Notes' },
  { value: 'best_time_to_call', label: 'Best Time to Call' },
  { value: 'tobacco', label: 'Tobacco?' },
  { value: 'medical', label: 'Medical Issues?' },
  { value: 'spanish', label: 'Spanish?' },
]


// ═══════════════════════════════════════════════
// SECTION 4 — Column Aliases (57 patterns, production-verified)
// ═══════════════════════════════════════════════

export const COLUMN_ALIASES = {
  // ── Names ──
  'full name': 'full_name', 'fullname': 'full_name', 'name': 'full_name',
  'borrowername': 'full_name', 'clientname': 'full_name', 'applicantname': 'full_name',
  'primaryname': 'full_name',
  'first name': 'first_name', 'firstname': 'first_name', 'fname': 'first_name',
  'first': 'first_name', 'borrowerfirstname': 'first_name', 'applicantfirstname': 'first_name',
  'clientfirstname': 'first_name', 'primaryfirstname': 'first_name',
  'last name': 'last_name', 'lastname': 'last_name', 'lname': 'last_name',
  'last': 'last_name', 'borrowerlastname': 'last_name', 'applicantlastname': 'last_name',
  'clientlastname': 'last_name', 'primarylastname': 'last_name',

  // ── Phone — primary (maps to `phone` which backend requires) ──
  // NOTE: 'mobile phone' and 'mobilephone' intentionally map to `phone` (primary),
  // NOT mobile_phone, because most vendor files label their only phone as "Mobile Phone"
  'phone': 'phone', 'phone1': 'phone', 'primaryphone': 'phone',
  'cell': 'phone', 'cell phone': 'phone', 'cellphone': 'phone',
  'mobile': 'phone', 'mphone': 'phone',
  'mobile phone': 'phone', 'mobilephone': 'phone', 'mobile_phone': 'phone',

  // ── Phone — secondary ──
  'home phone': 'home_phone', 'home_phone': 'home_phone', 'homephone': 'home_phone',
  'landline': 'home_phone', 'recentlandline1': 'home_phone',
  'phone2': 'home_phone', 'secondaryphone': 'home_phone', 'hphone': 'home_phone',
  'spouse phone': 'spouse_phone', 'spouse_phone': 'spouse_phone',
  'spousephone': 'spouse_phone', 'spouse cell': 'spouse_phone',

  // ── Email ──
  'email': 'email', 'e-mail': 'email', 'emailaddress': 'email',

  // ── Address ──
  'address': 'address', 'street': 'address', 'street address': 'address',
  'streetaddress': 'address', 'addr': 'address',
  'city': 'city', 'town': 'city',
  'county': 'county', 'county name': 'county', 'countyname': 'county',
  'state': 'state', 'st': 'state',
  'zip': 'zip_code', 'zip_code': 'zip_code', 'zipcode': 'zip_code',
  'zip code': 'zip_code', 'zip_plus_four': 'zip_code', 'postal': 'zip_code',
  'postalcode': 'zip_code',

  // ── DOB / Age ──
  'dob': 'dob', 'date of birth': 'dob', 'dateofbirth': 'dob',
  'birthdate': 'dob', 'birth_date': 'dob', 'birth date': 'dob',
  'birth year': 'birth_year', 'birth_year': 'birth_year', 'birthyear': 'birth_year',
  'age': 'birth_year', 'borrowerage': 'birth_year',

  // ── Lead metadata ──
  'source': 'lead_source', 'lead source': 'lead_source', 'lead_source': 'lead_source',
  'vendor': 'lead_source',
  'type': 'lead_type', 'lead type': 'lead_type', 'lead_type': 'lead_type',
  'lead age': 'lead_age_bucket', 'lead_age': 'lead_age_bucket',
  'lead_age_bucket': 'lead_age_bucket',

  // ── Money / Lender ──
  'lender': 'lender', 'mortgage company': 'lender', 'bank': 'lender', 'servicer': 'lender',
  'loan amount': 'loan_amount', 'loan_amount': 'loan_amount', 'loanamount': 'loan_amount',
  'mtg': 'loan_amount', 'mortgageamount': 'loan_amount', 'mortageamount': 'loan_amount',
  'mortgage': 'loan_amount',
  'mail date': 'mail_date', 'mail_date': 'mail_date', 'maildate': 'mail_date',

  // ── Notes / Best Time ──
  'notes': 'notes', 'note': 'notes',
  'best time to call': 'best_time_to_call', 'besttimetocall': 'best_time_to_call',
  'besttime': 'best_time_to_call', 'best_time': 'best_time_to_call',
  'comment': 'best_time_to_call', 'comments': 'best_time_to_call',

  // ── LPD ──
  'lpd': 'lpd', 'lead purchase date': 'lpd', 'purchasedate': 'lpd',

  // ── Flags ──
  'tobacco': 'tobacco', 'tobacco?': 'tobacco', 'tobaccouse': 'tobacco',
  'smoker': 'tobacco', 'borrowertobaccouse': 'tobacco',
  'medical': 'medical', 'medical issues': 'medical', 'medicalissues': 'medical',
  'medical issues?': 'medical', 'borrowermedicalissues': 'medical',
  'preexistingconditions': 'medical',
  'spanish': 'spanish', 'spanish?': 'spanish',

  // ── Gender ──
  'gender': 'gender', 'sex': 'gender', 'genderidentity': 'gender', 'gender_identity': 'gender',
}


// ═══════════════════════════════════════════════
// SECTION 5 — Wizard Step Labels
// ═══════════════════════════════════════════════

export const STEP_LABELS = {
  upload: 'Upload',
  fileConfig: 'File Config',
  mapping: 'Column Mapping',
  preview: 'Preview',
  importing: 'Importing',
  results: 'Results',
}


// ═══════════════════════════════════════════════
// SECTION 6 — Required Fields for Validation
// ═══════════════════════════════════════════════

/** Check if a column map satisfies minimum requirements for import */
export function isMappingValid(columnMap) {
  const vals = Object.values(columnMap).filter(Boolean)
  const hasPhone = vals.includes('phone') || vals.includes('mobile_phone') || vals.includes('home_phone')
  const hasName = (vals.includes('first_name') && vals.includes('last_name')) || vals.includes('full_name')
  return hasPhone && hasName
}

/** Get list of missing required fields for display */
export function getMissingRequired(columnMap) {
  const vals = Object.values(columnMap).filter(Boolean)
  const missing = []
  const hasName = (vals.includes('first_name') && vals.includes('last_name')) || vals.includes('full_name')
  const hasPhone = vals.includes('phone') || vals.includes('mobile_phone') || vals.includes('home_phone')
  if (!hasName) missing.push('Name (First + Last, or Full Name)')
  if (!hasPhone) missing.push('Phone')
  return missing
}

/** Required field keys that must be present in mapping */
export const REQUIRED_FIELD_KEYS = ['first_name', 'last_name', 'full_name', 'phone', 'mobile_phone', 'home_phone']


// ═══════════════════════════════════════════════
// SECTION 7 — Auto-Map Headers
// ═══════════════════════════════════════════════

/**
 * Auto-map spreadsheet headers to lead fields using aliases and exact matches.
 */
export function autoMapHeaders(hdrs) {
  const m = {}
  hdrs.forEach(h => {
    const lw = h.toLowerCase().trim()
    if (COLUMN_ALIASES[lw]) { m[h] = COLUMN_ALIASES[lw]; return }
    const match = LEAD_FIELDS.find(f => f.label.toLowerCase() === lw || f.value === lw)
    if (match) m[h] = match.value
  })
  return m
}


// ═══════════════════════════════════════════════
// SECTION 8 — Auto-Detect Vendor from Filename
// ═══════════════════════════════════════════════

/**
 * Auto-detect vendor/tier/leadType from filename patterns.
 */
export function autoDetectVendor(filename) {
  const fn = filename.toLowerCase()
  const out = { vendor: 'HOFLeads', tier: 'Diamond', leadType: 'Mortgage Protection', leadAge: '' }
  if (fn.includes('hof')) {
    out.vendor = 'HOFLeads'
    if (fn.includes('gold') || fn.includes('t2')) out.tier = 'Gold'
    else if (fn.includes('silver') || fn.includes('t3')) out.tier = 'Silver'
  } else if (fn.includes('proven')) { out.vendor = 'Proven Leads'; out.tier = 'N/A' }
  else if (fn.includes('aria')) { out.vendor = 'Aria Leads'; out.tier = 'Gold' }
  else if (fn.includes('milmo')) { out.vendor = 'MilMo'; out.tier = 'Gold' }
  else if (fn.includes('cheryl')) { out.vendor = 'Cheryl'; out.tier = 'T1' }
  if (fn.includes('final expense') || fn.includes('_fe_')) out.leadType = 'Final Expense'
  else if (fn.includes('annuity')) out.leadType = 'Annuity'
  else if (fn.includes('iul')) out.leadType = 'IUL'

  // Auto-detect lead age from filename (e.g. "proven_3m_batch.csv", "leads-6m.csv", "24-36m_list.xlsx")
  // Order matters: check range patterns before single values
  const ageMap = [
    { pattern: /\b(49[-–_]?60\s*m)\b/,  value: '49–60M' },
    { pattern: /\b(37[-–_]?48\s*m)\b/,  value: '37–48M' },
    { pattern: /\b(25[-–_]?36\s*m)\b/,  value: '25–36M' },
    { pattern: /\b(13[-–_]?24\s*m)\b/,  value: '13–24M' },
    { pattern: /\b(7[-–_]?12\s*m)\b/,   value: '7–12M'  },
    { pattern: /\b60\+?\s*m\b/,          value: '60+M'   },
    { pattern: /\b3\s*m\b/,              value: '3M'     },
    { pattern: /\b6\s*m\b/,              value: '6M'     },
  ]
  for (const { pattern, value } of ageMap) {
    if (pattern.test(fn)) { out.leadAge = value; break }
  }

  return out
}


// ═══════════════════════════════════════════════
// SECTION 9 — Build Leads from Parsed Rows
// ═══════════════════════════════════════════════

/**
 * Build lead objects from parsed rows, applying column mapping and batch metadata.
 *
 * Logic preserved from original:
 * - full_name splitting to first_name + last_name
 * - Phone fallback: mobile_phone → phone, home_phone → phone
 * - Boolean normalization for tobacco/medical/spanish
 * - 2-digit birth year correction (65→1965, 24→2024)
 * - Batch metadata applied only when row doesn't have its own value
 *
 * Returns { leads, droppedCount } — tracks rows missing required fields.
 */
export function buildLeads(rows, headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate) {
  const leads = []
  let droppedCount = 0
  for (const row of rows) {
    const lead = {}
    headers.forEach((h, i) => {
      const field = columnMap[h]
      if (field && row[i] !== undefined && row[i] !== null && String(row[i]).trim()) {
        // Normalize boolean fields from CSV strings
        if (['tobacco', 'medical', 'spanish'].includes(field)) {
          lead[field] = ['true','1','yes','y','x','si','sí'].includes(String(row[i]).trim().toLowerCase())
        } else {
          lead[field] = String(row[i]).trim()
        }
      }
    })

    // Full Name splitting — if CSV has no first_name/last_name but has full_name,
    // split on first space to extract first + last
    if (!lead.first_name && !lead.last_name && lead.full_name) {
      const parts = String(lead.full_name).trim().split(/\s+/)
      lead.first_name = parts[0] || ''
      lead.last_name = parts.slice(1).join(' ') || parts[0] || ''
      delete lead.full_name
    }

    // Phone fallback: if phone not mapped directly, promote mobile_phone or home_phone
    if (!lead.phone && lead.mobile_phone) lead.phone = lead.mobile_phone
    if (!lead.phone && lead.home_phone) lead.phone = lead.home_phone

    // Track dropped rows instead of silently skipping
    if (!lead.first_name || !lead.last_name || !lead.phone) {
      droppedCount++
      continue
    }

    // Apply batch metadata (only when row doesn't have its own value)
    if (vendor && !lead.lead_source) lead.lead_source = vendor + (tier && tier !== 'N/A' ? ' / ' + tier : '')
    if (leadType && !lead.lead_type) lead.lead_type = leadType
    if (leadAge && !lead.lead_age_bucket) lead.lead_age_bucket = leadAge
    if (purchaseDate && !lead.mail_date) lead.mail_date = purchaseDate
    if (tier && !lead.tier) lead.tier = tier
    if (purchaseDate && !lead.lpd) lead.lpd = purchaseDate

    // 2-digit birth year correction (e.g. "65" → 1965, "24" → 2024)
    if (lead.birth_year) {
      let yr = parseInt(lead.birth_year, 10)
      if (!isNaN(yr)) {
        if (yr >= 0 && yr <= 99) yr += yr >= 0 && yr <= 24 ? 2000 : 1900
        lead.birth_year = yr
      } else {
        lead.birth_year = undefined
      }
    }

    leads.push(lead)
  }
  return { leads, droppedCount }
}
