/**
 * Shared lead import utilities — constants, mapping, vendor detection, lead building.
 * Used by LeadImport.jsx (and previously LeadImportWizardModal.jsx, now deleted).
 */

export const VENDOR_TIERS = {
  'HOFLeads': ['Diamond', 'Gold', 'Silver'],
  'Proven Leads': ['N/A'],
  'Aria Leads': ['Gold', 'Silver', 'N/A'],
  'MilMo': ['Gold', 'Silver', 'N/A'],
  'Cheryl': ['T1', 'T2', 'T3', 'T4', 'T5'],
}

export const NEEDS_LEAD_AGE = {
  'HOFLeads': false,
  'Proven Leads': true,
  'Aria Leads': true,
  'MilMo': true,
  'Cheryl': true,
}

// Per-vendor age buckets — each vendor can have different bracket labels
export const VENDOR_AGE_BUCKETS = {
  'HOFLeads': [],
  'Proven Leads': ['7\u201312M', '13\u201324M', '25\u201336M', '37\u201348M', '49\u201360M', '60+M'],
  'Aria Leads': ['7\u201312M', '13\u201324M', '25\u201336M', '37\u201348M', '49\u201360M', '60+M'],
  'MilMo': ['7\u201312M', '13\u201324M', '25\u201336M', '37\u201348M', '49\u201360M', '60+M'],
  'Cheryl': ['T1', 'T2', 'T3', 'T4', 'T5'],
}

// Legacy fallback — kept for any code that imported LEAD_AGE_BUCKETS directly
export const LEAD_AGE_BUCKETS = ['7\u201312M', '13\u201324M', '25\u201336M', '37\u201348M', '49\u201360M', '60+M']

export const LEAD_TYPES = ['Mortgage Protection', 'Final Expense', 'Annuity', 'IUL']

export const LEAD_VENDORS = Object.keys(VENDOR_TIERS)

export const LEAD_FIELDS = [
  { value: 'first_name', label: 'First Name' },
  { value: 'last_name', label: 'Last Name' },
  { value: 'phone', label: 'Phone' },
  { value: 'home_phone', label: 'Home Phone' },
  { value: 'mobile_phone', label: 'Mobile Phone' },
  { value: 'spouse_phone', label: 'Spouse Phone' },
  { value: 'email', label: 'Email' },
  { value: 'address', label: 'Address' },
  { value: 'city', label: 'City' },
  { value: 'state', label: 'State' },
  { value: 'zip_code', label: 'ZIP Code' },
  { value: 'birth_year', label: 'Birth Year' },
  { value: 'lead_source', label: 'Lead Source' },
  { value: 'lead_type', label: 'Lead Type' },
  { value: 'lead_age_bucket', label: 'Lead Age Bucket' },
  { value: 'lender', label: 'Lender' },
  { value: 'loan_amount', label: 'Loan Amount' },
  { value: 'mail_date', label: 'Mail Date' },
  { value: 'notes', label: 'Notes' },
  { value: 'gender', label: 'Gender' },
  { value: 'home_phone', label: 'Home Phone' },
  { value: 'spouse_phone', label: 'Spouse Phone' },
  { value: 'best_time_to_call', label: 'Best Time to Call' },
  { value: 'dob', label: 'DOB (Full Date)' },
  { value: 'lpd', label: 'Lead Purchase Date (LPD)' },
  { value: 'tobacco', label: 'Tobacco?' },
  { value: 'medical', label: 'Medical Issues?' },
  { value: 'spanish', label: 'Spanish?' },
]

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
  // Any of these becomes the main phone field
  'phone': 'phone', 'phone1': 'phone', 'primaryphone': 'phone',
  'cell': 'phone', 'cell phone': 'phone', 'cellphone': 'phone',
  'mobile': 'phone', 'mphone': 'phone',
  // NOTE: 'mobile phone' and 'mobilephone' intentionally map to `phone` (primary),
  // NOT mobile_phone, because most vendor files label their only phone as "Mobile Phone"
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

export const STEP_LABELS = {
  source: 'Source', file: 'Upload', sheets: 'Sheets',
  mapping: 'Map Columns', metadata: 'Lead Details',
  preview: 'Preview', importing: 'Importing', results: 'Results',
}

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

/**
 * Auto-detect vendor/tier/leadType from filename patterns.
 */
export function autoDetectVendor(filename) {
  const fn = filename.toLowerCase()
  const out = { vendor: 'HOFLeads', tier: 'Diamond', leadType: 'Mortgage Protection' }
  if (fn.includes('hof')) {
    out.vendor = 'HOFLeads'
    if (fn.includes('gold') || fn.includes('t2')) out.tier = 'Gold'
    else if (fn.includes('silver') || fn.includes('t3')) out.tier = 'Silver'
  } else if (fn.includes('proven')) { out.vendor = 'Proven Leads'; out.tier = 'N/A' }
  else if (fn.includes('aria')) { out.vendor = 'Aria Leads'; out.tier = 'Gold' }
  else if (fn.includes('milmo')) { out.vendor = 'MilMo'; out.tier = 'Gold' }
  if (fn.includes('final expense') || fn.includes('_fe_')) out.leadType = 'Final Expense'
  else if (fn.includes('annuity')) out.leadType = 'Annuity'
  else if (fn.includes('iul')) out.leadType = 'IUL'
  return out
}

/**
 * Build lead objects from parsed rows, applying column mapping and batch metadata.
 *
 * BUG 9 FIX: Only apply batch leadAge if the row doesn't already have a lead_age_bucket value.
 * BUG 12 FIX: Returns { leads, droppedCount } — tracks rows missing required fields.
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
    // RISK FIX: Full Name splitting — if CSV has no first_name/last_name but has 'name'/'full_name',
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

    // BUG 12: Track dropped rows instead of silently skipping
    if (!lead.first_name || !lead.last_name || !lead.phone) {
      droppedCount++
      continue
    }
    if (vendor && !lead.lead_source) lead.lead_source = vendor + (tier && tier !== 'N/A' ? ' / ' + tier : '')
    if (leadType && !lead.lead_type) lead.lead_type = leadType
    // BUG 9 FIX: Only apply batch lead age if row doesn't already have one
    if (leadAge && !lead.lead_age_bucket) lead.lead_age_bucket = leadAge
    if (purchaseDate && !lead.mail_date) lead.mail_date = purchaseDate
    // Field-parity: tier and LPD from wizard-level metadata
    if (tier && !lead.tier) lead.tier = tier
    if (purchaseDate && !lead.lpd) lead.lpd = purchaseDate
    // RISK FIX: 2-digit birth year (e.g. "65" → 1965, not 65)
    if (lead.birth_year) {
      let yr = parseInt(lead.birth_year, 10)
      if (!isNaN(yr)) {
        if (yr >= 0 && yr <= 99) yr += yr >= 0 && yr <= 24 ? 2000 : 1900  // 65→1965, 24→2024
        lead.birth_year = yr
      } else {
        lead.birth_year = undefined
      }
    }
    leads.push(lead)
  }
  return { leads, droppedCount }
}
