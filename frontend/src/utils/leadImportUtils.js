/**
 * Shared lead import utilities — constants, mapping, vendor detection, lead building.
 * Used by LeadImport.jsx (and previously LeadImportWizardModal.jsx, now deleted).
 */

export const VENDOR_TIERS = {
  'HOFLeads': ['Diamond', 'Gold', 'Silver'],
  'Proven Leads': ['N/A'],
  'Aria Leads': ['Gold', 'Silver', 'N/A'],
  'MilMo': ['Gold', 'Silver', 'N/A'],
}

export const NEEDS_LEAD_AGE = {
  'HOFLeads': false,
  'Proven Leads': true,
  'Aria Leads': true,
  'MilMo': true,
}

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
]

export const COLUMN_ALIASES = {
  'first name': 'first_name', 'firstname': 'first_name', 'fname': 'first_name',
  'last name': 'last_name', 'lastname': 'last_name', 'lname': 'last_name',
  'phone': 'phone', 'cell': 'phone', 'cell phone': 'phone', 'mobile': 'phone', 'mobile phone': 'phone',
  'home phone': 'home_phone', 'home_phone': 'home_phone', 'homephone': 'home_phone', 'hphone': 'home_phone',
  'mobile phone': 'mobile_phone', 'mobile_phone': 'mobile_phone', 'mobilephone': 'mobile_phone',
  'spouse phone': 'spouse_phone', 'spouse_phone': 'spouse_phone', 'spousephone': 'spouse_phone', 'spouse cell': 'spouse_phone',
  'email': 'email', 'e-mail': 'email',
  'address': 'address', 'street': 'address', 'street address': 'address',
  'city': 'city', 'state': 'state', 'st': 'state',
  'zip': 'zip_code', 'zip_code': 'zip_code', 'zipcode': 'zip_code', 'zip code': 'zip_code', 'postal': 'zip_code',
  'birth year': 'birth_year', 'birth_year': 'birth_year', 'birthyear': 'birth_year', 'dob': 'birth_year',
  'source': 'lead_source', 'lead source': 'lead_source', 'lead_source': 'lead_source', 'vendor': 'lead_source',
  'type': 'lead_type', 'lead type': 'lead_type', 'lead_type': 'lead_type',
  'lead age': 'lead_age_bucket', 'lead_age': 'lead_age_bucket', 'lead_age_bucket': 'lead_age_bucket',
  'lender': 'lender', 'mortgage company': 'lender',
  'loan amount': 'loan_amount', 'loan_amount': 'loan_amount', 'loanamount': 'loan_amount',
  'mail date': 'mail_date', 'mail_date': 'mail_date', 'maildate': 'mail_date',
  'notes': 'notes', 'note': 'notes', 'comments': 'notes',
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
        lead[field] = String(row[i]).trim()
      }
    })
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
    if (lead.birth_year) { const yr = parseInt(lead.birth_year, 10); lead.birth_year = isNaN(yr) ? undefined : yr }
    leads.push(lead)
  }
  return { leads, droppedCount }
}
