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
  'HOFLeads':       ['Diamond', 'Gold', 'Silver'],
  'Proven Leads':   ['N/A'],
  'Aria Leads':     ['Gold', 'Silver', 'N/A'],
  'StrongPoint':    ['N/A'],
  'MilMo':          ['Gold', 'Silver', 'N/A'],
  'Cheryl':         ['T1', 'T2', 'T3', 'T4', 'T5'],
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
  'Proven Leads':  ['3M', '6M', '7-12M', '13-24M', '25-36M', '37-48M', '49-60M', '60+M'],
  'Aria Leads':    ['7-12M', '13-24M', '25-36M', '37-48M', '49-60M', '60+M'],
  'MilMo':         ['7-12M', '13-24M', '25-36M', '37-48M', '49-60M', '60+M'],
  'Cheryl':        ['T1', 'T2', 'T3', 'T4', 'T5'],
}


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

  // Spouse
  { value: 'spouse_dob', label: 'Spouse DOB' },
  { value: 'spouse_age', label: 'Spouse Age' },

  // Lead metadata
  { value: 'lead_source', label: 'Lead Source' },
  { value: 'lead_type', label: 'Lead Type' },
  { value: 'lead_age_bucket', label: 'Lead Age' },
  { value: 'lpd', label: 'Lead Purchase Date (LPD)' },
  { value: 'lead_received', label: 'Lead Received Date' },
  { value: 'vendor_lead_id', label: 'Vendor Lead ID' },

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
  'birthdate 1': 'dob', 'birthdate1': 'dob',  // Cheryl vendor format
  'birth year': 'birth_year', 'birth_year': 'birth_year', 'birthyear': 'birth_year',
  'age': 'birth_year', 'borrowerage': 'birth_year',
  'age1': 'birth_year',  // Cheryl vendor format (redundant if BIRTHDATE 1 mapped, but safe)

  // ── Spouse DOB / Age ──
  'birthdate 2': 'spouse_dob', 'birthdate2': 'spouse_dob',  // Cheryl vendor format
  'spouse dob': 'spouse_dob', 'spouse_dob': 'spouse_dob',
  'spouse birthdate': 'spouse_dob', 'spouse birth date': 'spouse_dob',
  'co dob': 'spouse_dob',
  'coborrower dob': 'spouse_dob', 'co-borrower dob': 'spouse_dob',
  'age2': 'spouse_age',  // Cheryl vendor format
  'spouse age': 'spouse_age', 'spouse_age': 'spouse_age',
  'co age': 'spouse_age', 'coborrower age': 'spouse_age',

  // ── Lead metadata ──
  'source': 'lead_source', 'lead source': 'lead_source', 'lead_source': 'lead_source',
  'vendor': 'lead_source',
  'type': 'lead_type', 'lead type': 'lead_type', 'lead_type': 'lead_type',
  'lead age': 'lead_age_bucket', 'lead_age': 'lead_age_bucket',
  'lead_age_bucket': 'lead_age_bucket', 'lage': 'lead_age_bucket',

  // ── Money / Lender ──
  'lender': 'lender', 'mortgage company': 'lender', 'bank': 'lender', 'servicer': 'lender',
  'loan amount': 'loan_amount', 'loan_amount': 'loan_amount', 'loanamount': 'loan_amount',
  'mtg': 'loan_amount', 'mortgageamount': 'loan_amount', 'mortageamount': 'loan_amount',
  'mortgage': 'loan_amount',
  'mtg amt': 'loan_amount', 'mtgamt': 'loan_amount',  // Cheryl vendor format
  'mail date': 'mail_date', 'mail_date': 'mail_date', 'maildate': 'mail_date',
  'closing date': 'mail_date', 'closingdate': 'mail_date',  // Cheryl vendor format (closest FC equivalent)

  // ── Notes / Best Time ──
  'notes': 'notes', 'note': 'notes',
  'best time to call': 'best_time_to_call', 'besttimetocall': 'best_time_to_call',
  'besttime': 'best_time_to_call', 'best_time': 'best_time_to_call',
  'comment': 'best_time_to_call', 'comments': 'best_time_to_call',

  // ── LPD ──
  'lpd': 'lpd', 'lead purchase date': 'lpd', 'purchasedate': 'lpd',
  'delivery date': 'lpd', 'deliverydate': 'lpd',  // Cheryl vendor format

  // ── Lead Received Date ──
  'call in date': 'lead_received', 'call_in_date': 'lead_received', 'callindate': 'lead_received',  // Aria vendor
  'lead received': 'lead_received', 'lead_received': 'lead_received',
  'date lead rcvd': 'lead_received', 'date lead received': 'lead_received',  // Cheryl vendor (received date, not purchase date)

  // ── Vendor Lead ID ──
  'lead_id': 'vendor_lead_id', 'lead id': 'vendor_lead_id', 'leadid': 'vendor_lead_id',
  'vendor lead id': 'vendor_lead_id', 'vendor_lead_id': 'vendor_lead_id',
  'external id': 'vendor_lead_id', 'external_id': 'vendor_lead_id',
  'orderid': 'vendor_lead_id',

  // ── Flags ──
  'tobacco': 'tobacco', 'tobacco?': 'tobacco', 'tobaccouse': 'tobacco',
  'smoker': 'tobacco', 'borrowertobaccouse': 'tobacco',
  'tobacco 1': 'tobacco', 'tobacco1': 'tobacco',  // Cheryl vendor format
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
  const hasDupes = getDuplicateMappings(columnMap).length > 0
  return hasPhone && hasName && !hasDupes
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

/**
 * Return list of FC field names that are mapped to more than once.
 * phone/home_phone/mobile_phone are intentionally allowed to overlap (phone fallback chain).
 * first_name/last_name/full_name are allowed to overlap (name split path).
 */
export function getDuplicateMappings(columnMap) {
  const ALLOWED_DUPES = new Set(['phone', 'home_phone', 'mobile_phone', 'first_name', 'last_name', 'full_name'])
  const counts = {}
  Object.values(columnMap).forEach(v => {
    if (v && !ALLOWED_DUPES.has(v)) counts[v] = (counts[v] || 0) + 1
  })
  return Object.keys(counts).filter(k => counts[k] > 1)
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
  else if (fn.includes('scl') || fn.includes('cheryl')) { out.vendor = 'Cheryl'; out.tier = 'T1' }
  if (fn.includes('final expense') || fn.includes('_fe_')) out.leadType = 'Final Expense'
  else if (fn.includes('annuity')) out.leadType = 'Annuity'
  else if (fn.includes('iul')) out.leadType = 'IUL'

  // Auto-detect lead age from filename (e.g. "proven_3m_batch.csv", "leads-6m.csv", "24-36m_list.xlsx")
  // Order matters: check range patterns before single values
  const ageMap = [
    { pattern: /\b(49[-–_]?60\s*m)\b/,  value: '49-60M' },
    { pattern: /\b(37[-–_]?48\s*m)\b/,  value: '37-48M' },
    { pattern: /\b(25[-–_]?36\s*m)\b/,  value: '25-36M' },
    { pattern: /\b(13[-–_]?24\s*m)\b/,  value: '13-24M' },
    { pattern: /\b(7[-–_]?12\s*m)\b/,   value: '7-12M'  },
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
// SECTION 8b — Date Normalization Helper
// ═══════════════════════════════════════════════

/**
 * Normalize a date value to YYYY-MM-DD string.
 * Handles: JS Date objects (SheetJS cellDates:true), Excel serial numbers
 * (SheetJS default), ISO strings, M/D/YYYY strings, and YYYY-MM-DD strings.
 * Returns the original string if format is unrecognized (let backend handle it).
 */
function normalizeDateValue(val) {
  if (!val) return val
  // JS Date object (from SheetJS with cellDates:true)
  if (val instanceof Date && !isNaN(val.getTime())) {
    return val.toISOString().slice(0, 10)
  }
  const s = String(val).trim()
  // Already YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s
  // M/D/YYYY — convert to YYYY-MM-DD (required for getCherylTier and backend consistency)
  const mdyFull = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/)
  if (mdyFull) {
    return `${mdyFull[3]}-${mdyFull[1].padStart(2, '0')}-${mdyFull[2].padStart(2, '0')}`
  }
  // M/D/YY — convert to YYYY-MM-DD with century correction
  const mdyShort = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2})$/)
  if (mdyShort) {
    const yr = parseInt(mdyShort[3], 10)
    const fullYear = yr >= 50 ? 1900 + yr : 2000 + yr
    return `${fullYear}-${mdyShort[1].padStart(2, '0')}-${mdyShort[2].padStart(2, '0')}`
  }
  // Excel serial date number (integer > 100 and < 200000, no other chars)
  const n = Number(s)
  if (Number.isFinite(n) && n > 100 && n < 200000 && /^\d+$/.test(s)) {
    // Excel epoch: Jan 0 1900 = day 1, with the Lotus 1-2-3 Feb 29 1900 bug
    const epoch = new Date(Date.UTC(1899, 11, 30))
    const d = new Date(epoch.getTime() + n * 86400000)
    if (!isNaN(d.getTime())) return d.toISOString().slice(0, 10)
  }
  // Unrecognized — return as-is and let backend try
  return s
}

/** Fields that contain date values and should be normalized */
const DATE_FIELDS = ['dob', 'mail_date', 'lpd', 'lead_received', 'spouse_dob']

/**
 * Determine Cheryl vendor tier from lead_received date.
 * Cheryl Partner Pricing (SCL IMG):
 *   T1: 2025-06-01 – 2025-11-30
 *   T2: 2024-03-01 – 2025-05-31
 *   T3: 2021-03-01 – 2024-02-29
 *   T4: 2019-03-01 – 2021-02-28
 *   T5: 2016-03-01 – 2019-02-28
 *
 * Sample verifications from SCL_IMG file:
 *   John Hilton:       2025-02-20 → T2
 *   Jacob Stern:       2025-08-11 → T1
 *   Dale Mackenstadt:  2025-11-05 → T1
 *   Charles Saksa:     2025-11-07 → T1
 */
function getCherylTier(dateStr) {
  if (!dateStr) return null
  const d = new Date(dateStr + 'T00:00:00')  // force local midnight parse
  if (isNaN(d)) return null
  const ymd = d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate()
  if (ymd >= 20250601 && ymd <= 20251130) return 'T1'
  if (ymd >= 20240301 && ymd <= 20250531) return 'T2'
  if (ymd >= 20210301 && ymd <= 20240229) return 'T3'
  if (ymd >= 20190301 && ymd <= 20210228) return 'T4'
  if (ymd >= 20160301 && ymd <= 20190228) return 'T5'
  return null
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
export function buildLeads(rows, headers, columnMap, vendor, tier, leadType, leadAge, purchaseDate, adjustAge = false) {
  const leads = []
  let droppedCount = 0
  const droppedRows = []
  for (const row of rows) {
    const lead = {}
    headers.forEach((h, i) => {
      const field = columnMap[h]
      if (field && row[i] !== undefined && row[i] !== null && String(row[i]).trim()) {
        // Normalize choice fields for Close.com (Yes/No strings, not booleans)
        if (['tobacco', 'spanish'].includes(field)) {
          const v = String(row[i]).trim().toLowerCase()
          lead[field] = ['true','1','yes','y','x','si','sí'].includes(v) ? 'Yes' : 'No'
        } else if (field === 'medical') {
          // Medical Issues is a text field in Close — keep raw value
          lead[field] = String(row[i]).trim()
        } else if (DATE_FIELDS.includes(field)) {
          // Date fields: normalize from raw value (handles Date objects, serial numbers, strings)
          lead[field] = normalizeDateValue(row[i])
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

    // Normalize gender to Close.com choices (M/F)
    if (lead.gender) {
      const g = String(lead.gender).trim().toLowerCase()
      if (g === 'male' || g === 'm') lead.gender = 'M'
      else if (g === 'female' || g === 'f') lead.gender = 'F'
      else delete lead.gender  // Close only accepts M or F
    }

    // Phone fallback: if phone not mapped directly, promote mobile_phone or home_phone
    if (!lead.phone && lead.mobile_phone) lead.phone = lead.mobile_phone
    if (!lead.phone && lead.home_phone) lead.phone = lead.home_phone

    // Normalize date fields — SheetJS may return Excel serial numbers or Date objects
    // instead of strings, which would fail backend parsing. Convert to YYYY-MM-DD.
    for (const df of DATE_FIELDS) {
      if (lead[df]) lead[df] = normalizeDateValue(lead[df])
    }

    // Track dropped rows with reason and original raw data
    if (!lead.first_name || !lead.last_name || !lead.phone) {
      const missing = []
      if (!lead.first_name) missing.push('first_name')
      if (!lead.last_name) missing.push('last_name')
      if (!lead.phone) missing.push('phone')
      const rawObj = {}
      headers.forEach((h, i) => { if (row[i] != null && String(row[i]).trim()) rawObj[h] = String(row[i]).trim() })
      droppedRows.push({ reason: 'Missing: ' + missing.join(', '), raw: rawObj })
      droppedCount++
      continue
    }

    // Vendor Lead ID: force to string (may come as large integer from CSV)
    if (lead.vendor_lead_id) lead.vendor_lead_id = String(lead.vendor_lead_id)

    // Spouse Age: cast to int, drop if invalid/zero
    if (lead.spouse_age) {
      const sa = parseInt(lead.spouse_age, 10)
      if (isNaN(sa) || sa === 0) { delete lead.spouse_age } else { lead.spouse_age = sa }
    }

    // Cheryl: strip fields that are her internal metrics, not meaningful for Close
    if (vendor === 'Cheryl') {
      delete lead.lead_type
      delete lead.vendor_lead_id
    }

    // Apply batch metadata (only when row doesn't have its own value)
    if (leadType && !lead.lead_type && vendor !== 'Cheryl') lead.lead_type = leadType
    if (leadAge && !lead.lead_age_bucket) lead.lead_age_bucket = leadAge
    if (purchaseDate && !lead.mail_date) lead.mail_date = purchaseDate
    // Cheryl: auto-assign tier from lead_received date (overrides file-level tier)
    // Must happen BEFORE lead_source is built so the correct per-row tier is used
    if (vendor === 'Cheryl' && lead.lead_received) {
      const cherylTier = getCherylTier(lead.lead_received)
      if (cherylTier) lead.tier = cherylTier
    }
    if (tier && !lead.tier) lead.tier = tier
    // Build lead_source AFTER tier is resolved so it reflects the correct per-row tier
    if (vendor && !lead.lead_source) lead.lead_source = vendor + (lead.tier && lead.tier !== 'N/A' ? ' / ' + lead.tier : '')
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

    // Age adjustment from lead age bucket (only when adjustAge=true and we have what we need)
    if (adjustAge && lead.birth_year) {
      const currentYear = new Date().getFullYear()
      const ageOnFile = currentYear - lead.birth_year  // reverse: birth_year was set from age column
      const lpd = lead.lpd || lead.mail_date || purchaseDate
      const lage = lead.lead_age_bucket || leadAge
      if (ageOnFile > 0 && lpd && lage) {
        const estimated = estimateCurrentAge(ageOnFile, lpd, lage)
        if (estimated !== null) {
          lead.birth_year = currentYear - estimated  // store as birth_year for backend
        }
      }
    }

    leads.push(lead)
  }
  return { leads, droppedCount, droppedRows }
}


/**
 * Estimate current age from age-at-mailer + LPD + lead age bucket.
 *
 * Logic:
 *   lead_creation_date = lpd - lage_midpoint_months
 *   years_elapsed = (today - lead_creation_date) / 365.25
 *   current_age = Math.floor(age_at_mailer + years_elapsed)
 *
 * Returns null if any required input is missing or unparseable.
 * Rounds DOWN — people prefer being told they're younger.
 */
export function estimateCurrentAge(ageAtMailer, lpd, lageBucket) {
  if (!ageAtMailer || !lpd || !lageBucket) return null

  const age = parseInt(ageAtMailer, 10)
  if (isNaN(age) || age < 18 || age > 120) return null

  // Parse LPD
  const lpdDate = new Date(lpd)
  if (isNaN(lpdDate.getTime())) return null

  // Parse lage bucket midpoint
  const lageNorm = lageBucket.toLowerCase().replace(/\s/g, '').replace(/[–—]/g, '-')
  let avgMonths = null
  const rangeMatch = lageNorm.match(/^(\d+)-(\d+)/)
  if (rangeMatch) {
    avgMonths = (parseInt(rangeMatch[1], 10) + parseInt(rangeMatch[2], 10)) / 2
  } else {
    const singleMatch = lageNorm.match(/^(\d+)/)
    if (singleMatch) avgMonths = parseInt(singleMatch[1], 10)
  }
  if (avgMonths === null) return null

  // Lead creation date = LPD - avgMonths
  const leadCreationDate = new Date(lpdDate)
  leadCreationDate.setDate(leadCreationDate.getDate() - Math.round(avgMonths * 30.44))

  // Years elapsed from lead creation to today
  const today = new Date()
  const yearsElapsed = (today - leadCreationDate) / (365.25 * 24 * 60 * 60 * 1000)

  return Math.floor(age + yearsElapsed)
}
