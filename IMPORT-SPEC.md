# IMPORT-SPEC.md — FalconConnect v3 Lead Import Rebuild

**Author:** Dolf (Analyzer Agent)  
**Date:** 2026-03-11  
**Status:** Ready for Builder  
**Scope:** Complete rewrite of `LeadImport.jsx` + supporting utils. Backend changes minimal (endpoint already correct).

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Multi-CSV Batch Import](#2-multi-csv-batch-import)
3. [Clean Column Mapping UI](#3-clean-column-mapping-ui)
4. [Metadata Step (Per-File)](#4-metadata-step-per-file)
5. [Full 3-System Pipeline](#5-full-3-system-pipeline)
6. [Field Parity — Complete Map](#6-field-parity--complete-map)
7. [Error Handling & Rate Limiting](#7-error-handling--rate-limiting)
8. [Edge Cases & Normalizations](#8-edge-cases--normalizations)
9. [UI/UX Design Spec](#9-uiux-design-spec)
10. [File Structure](#10-file-structure)
11. [Backend Changes Required](#11-backend-changes-required)

---

## 1. Architecture Overview

### Current Flow (Single File)
```
Source → Parse → Map Columns → Metadata → Preview → Import → Results
```

### New Flow (Multi-File Batch)
```
Source → Add Files → Per-File Metadata Table → Shared Column Mapping → Preview → Sequential Import → Grand Summary
```

### Key Principles
- **One wizard run** handles 1–N CSV files
- Each file gets its **own metadata** (vendor, tier, lead type, age bracket, purchase date)
- Column mapping is **per-file** (different CSVs may have different headers)
- Import is **sequential**: file 1 completes before file 2 starts
- **Notion → GHL → Quo** pipeline per row (unchanged from current backend)
- Dry run and test mode toggles remain global (apply to all files)

### Tech Stack (No Changes)
- Frontend: React (Vite), XLSX.js for parsing
- Backend: FastAPI `POST /api/leads/bulk` (authenticated via Clerk)
- Services: Notion API, GHL API, Quo/OpenPhone API

---

## 2. Multi-CSV Batch Import

### 2.1 File Addition

**Drop zone accepts multiple files.** User can also click to browse and select multiple.

```
Accepted: .csv, .xlsx, .xls, .tsv
Max files: No hard limit (recommend warning at 10+)
```

Each file is parsed immediately on drop/select using `XLSX.read()`. If parsing fails, show inline error on that file row — don't block other files.

### 2.2 File Queue Table

After files are added, show a table with columns:

| # | Filename | Rows | Vendor | Tier | Lead Type | Age Bracket | Purchase Date | Status | Actions |
|---|----------|------|--------|------|-----------|-------------|---------------|--------|---------|
| 1 | hof-diamond-batch.csv | 247 | HOFLeads | Diamond | Mortgage Protection | — | 2026-03-10 | Ready | Edit / Remove |
| 2 | cheryl-t3-aged.csv | 89 | Cheryl | T3 | Final Expense | T3 | 2026-03-01 | Ready | Edit / Remove |
| 3 | proven-feb.csv | 156 | Proven Leads | N/A | Mortgage Protection | 13–24M | 2026-02-15 | Ready | Edit / Remove |

**Auto-detection:** On file add, run `autoDetectVendor(filename)` to pre-fill Vendor/Tier/Lead Type. User can edit inline or via a metadata modal.

**Status values:** `Parsing...` → `Ready` → `Mapping...` → `Importing...` → `✓ Done (X created, Y failed)` → `✗ Error`

**Actions:**
- **Edit** — opens metadata editor for that file
- **Remove** — removes file from queue (with confirmation if already mapped)

### 2.3 Per-File Metadata

Each file row has editable metadata fields. Two approaches (Builder chooses):

**Option A — Inline editing:** Dropdown/inputs directly in the table cells.  
**Option B — Edit modal:** Click "Edit" to open a small modal with the metadata form (same fields as current metadata step).

Metadata fields per file:
- `vendor` — select from `LEAD_VENDORS` (HOFLeads, Proven Leads, Aria Leads, MilMo, Cheryl)
- `tier` — select from `VENDOR_TIERS[vendor]` (dynamic based on vendor)
- `leadType` — select from `LEAD_TYPES` (Mortgage Protection, Final Expense, Annuity, IUL)
- `leadAge` — select from `VENDOR_AGE_BUCKETS[vendor]` (only shown when `NEEDS_LEAD_AGE[vendor]` is true)
- `purchaseDate` — date input

### 2.4 Per-File Column Mapping

Each file may have different CSV columns. When user clicks "Map Columns" on a file (or advances to the mapping step), show the column mapping UI for that specific file.

**Column mapping state is stored per-file:**
```js
files: [
  {
    file: File,
    fileName: "hof-diamond-batch.csv",
    headers: ["First Name", "Last Name", "Phone", ...],
    parsedRows: [[...], [...], ...],
    columnMap: { "First Name": "first_name", "Last Name": "last_name", ... },
    vendor: "HOFLeads",
    tier: "Diamond",
    leadType: "Mortgage Protection",
    leadAge: "",
    purchaseDate: "2026-03-10",
    status: "ready",  // parsing | ready | mapping | importing | done | error
    result: null,      // { created, updated, failed, errors, ghlWarnings, droppedCount }
  },
  ...
]
```

### 2.5 Sequential Import

When user clicks "Import All":
1. Process files in order (file[0], then file[1], etc.)
2. For each file: call `buildLeads()` → batch to `/api/leads/bulk` in chunks of 50
3. Update file status in real-time: `Importing... (47/247)`
4. On file completion: show per-file result summary inline
5. If a file fails catastrophically (network error), mark it as `error` and continue to next file
6. After all files: show grand total summary

### 2.6 Grand Total Summary

After all files complete:

```
Import Complete — 3 Files Processed

Total: 492 leads
├─ Created: 478
├─ Updated: 6
├─ Failed: 8
├─ GHL Warnings: 3
├─ Quo Synced: 471
└─ Dropped (missing fields): 12

Per-File Breakdown:
  hof-diamond-batch.csv  — 247 created, 0 failed
  cheryl-t3-aged.csv     — 85 created, 4 failed
  proven-feb.csv         — 146 created, 4 failed, 6 updated
```

---

## 3. Clean Column Mapping UI

### 3.1 Current Problems
- All dropdowns crammed in a single scrollable list
- No sample data visible
- No visual distinction between mapped/unmapped
- Required fields not highlighted
- Hard to scan which columns are mapped

### 3.2 New Design: 2-Column Mapping Table

```
┌─────────────────────────────────────────────────────────────────────┐
│  CSV Column              Sample Data           FC Field             │
├─────────────────────────────────────────────────────────────────────┤
│  ✓ First Name           "John"                [First Name     ▾]   │  ← green row, auto-mapped
│  ✓ Last Name            "Smith"               [Last Name      ▾]   │  ← green row, auto-mapped
│  ✓ Phone                "602-555-1234"        [Phone          ▾]   │  ← green row, auto-mapped
│  ✓ Email                "john@gmail.com"      [Email          ▾]   │  ← green row, auto-mapped
│  ✓ Address              "123 Main St"         [Address        ▾]   │  ← green row, auto-mapped
│  ✓ City                 "Phoenix"             [City           ▾]   │  ← green row, auto-mapped
│  ✓ State                "AZ"                  [State          ▾]   │  ← green row, auto-mapped
│  ✓ Zip                  "85001"               [ZIP Code       ▾]   │  ← green row, auto-mapped
│  — Lender               "Chase"               [— skip —       ▾]   │  ← muted row, unmapped
│  — Loan Amount          "$250,000"            [— skip —       ▾]   │  ← muted row, unmapped
│  — MTG                  "$1,200"              [— skip —       ▾]   │  ← muted row, unmapped
│  — Best Time            "Morning"             [— skip —       ▾]   │  ← muted row, unmapped
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 Visual Rules

| State | Row Background | Icon | Text Color |
|-------|---------------|------|------------|
| Auto-mapped (from aliases) | `oklch(14% 0.02 145 / 0.15)` (subtle green tint) | `✓` green checkmark | Normal text |
| Manually mapped | `oklch(14% 0.02 85 / 0.15)` (subtle amber tint) | `✓` amber checkmark | Normal text |
| Unmapped (skipped) | Default surface | `—` dash, muted | `var(--text-muted)` |
| Required field (mapped) | Green tint + left border accent | `✓` green | Normal |
| Required field (NOT mapped) | `oklch(15% 0.04 25 / 0.2)` (subtle red tint) | `!` red indicator | `var(--red)` |

### 3.4 Required Fields Indicator

At the top of the mapping section, show a validation bar:

```
Required: First Name ✓  Last Name ✓  Phone ✓        ← all green = can proceed
Required: First Name ✓  Last Name ✗  Phone ✗        ← red = button disabled
```

The requirement is: at least one phone field (phone, mobile_phone, or home_phone) AND name coverage ((first_name + last_name) OR full_name). This matches the existing `mappingOk` logic.

### 3.5 Sample Data Column

Show the first non-empty value from the parsed rows for each CSV column. This helps users understand what data is in each column to map correctly.

```js
// For each header, find first non-empty value
const sampleValue = parsedRows.find(row => row[colIndex])?.[colIndex] || "—"
```

Display truncated to ~30 chars with ellipsis.

### 3.6 Sorting

Mapped columns sort to top, unmapped to bottom. Within each group, preserve original CSV column order.

---

## 4. Metadata Step (Per-File)

### 4.1 Fields

These are set per-file in the file queue table (Section 2.3). No separate "metadata step" in the wizard — it's integrated into the file queue.

| Field | Type | Options | Default |
|-------|------|---------|---------|
| Vendor | Select | HOFLeads, Proven Leads, Aria Leads, MilMo, Cheryl | Auto-detected from filename |
| Tier | Select | Dynamic per vendor (see `VENDOR_TIERS`) | First tier for detected vendor |
| Lead Type | Select | Mortgage Protection, Final Expense, Annuity, IUL | Mortgage Protection |
| Lead Age Bucket | Select | Dynamic per vendor (see `VENDOR_AGE_BUCKETS`) | Empty (only shown when `NEEDS_LEAD_AGE[vendor]`) |
| Purchase Date | Date | Date picker | Empty |

### 4.2 Vendor → Tier Mapping (from `leadImportUtils.js`)

```js
VENDOR_TIERS = {
  'HOFLeads':      ['Diamond', 'Gold', 'Silver'],
  'Proven Leads':  ['N/A'],
  'Aria Leads':    ['Gold', 'Silver', 'N/A'],
  'MilMo':         ['Gold', 'Silver', 'N/A'],
  'Cheryl':        ['T1', 'T2', 'T3', 'T4', 'T5'],
}
```

### 4.3 Vendor → Age Bucket Mapping

```js
NEEDS_LEAD_AGE = {
  'HOFLeads': false,
  'Proven Leads': true,
  'Aria Leads': true,
  'MilMo': true,
  'Cheryl': true,
}

VENDOR_AGE_BUCKETS = {
  'HOFLeads':      [],
  'Proven Leads':  ['7–12M', '13–24M', '25–36M', '37–48M', '49–60M', '60+M'],
  'Aria Leads':    ['7–12M', '13–24M', '25–36M', '37–48M', '49–60M', '60+M'],
  'MilMo':         ['7–12M', '13–24M', '25–36M', '37–48M', '49–60M', '60+M'],
  'Cheryl':        ['T1', 'T2', 'T3', 'T4', 'T5'],
}
```

---

## 5. Full 3-System Pipeline

### 5.1 Write Order (Non-Negotiable)

```
For each lead row:
  1. NOTION (source of truth)
     ├─ Success → continue to GHL
     └─ Failure → SKIP ROW ENTIRELY (count as failed, log error)

  2. GHL (automations)
     ├─ Success → continue to Quo
     └─ Failure → log as GHL warning, count lead as SUCCESS (it's in Notion)
     After GHL: update Notion page with GHL Contact ID (cross-reference)

  3. QUO (dialer)
     ├─ Success → increment quo_synced counter
     └─ Failure → log warning, non-fatal
```

This is already implemented in `routers/leads.py` → `bulk_import_leads()`. No backend changes needed for the pipeline.

### 5.2 Test Mode

When `test_mode=true` (sent in request body):
- Tier is overridden to `"TEST"` in the lead dict
- Lead source gets `"[TEST]"` prefix: `"[TEST] HOFLeads / Diamond"`
- GHL gets `"test-import"` tag (in addition to the import date tag)
- Quo receives the lead normally (no test flag — Quo doesn't have tagging)

**Purpose:** Easy to find and bulk-delete test records from Notion + GHL.

### 5.3 Dry Run

When `dry_run=true` (sent in request body):
- Backend validates each lead (schema validation runs)
- Backend counts each valid lead as "created" without making any API calls
- No writes to Notion, GHL, or Quo
- Frontend shows results as "Dry Run Complete — No data was written"

---

## 6. Field Parity — Complete Map

### 6.1 All FC Lead Fields (Frontend → Backend → Services)

#### CSV Mappable Fields (LEAD_FIELDS array)

| FC Field Key | Label | Type | Notes |
|---|---|---|---|
| `first_name` | First Name | string | **Required** (or full_name) |
| `last_name` | Last Name | string | **Required** (or full_name) |
| `full_name` | Full Name | string | Split to first+last if no first/last mapped |
| `phone` | Phone | string | **Required** (or mobile_phone/home_phone) |
| `home_phone` | Home Phone | string | Falls back to phone if phone unmapped |
| `mobile_phone` | Mobile Phone | string | Falls back to phone if phone unmapped |
| `spouse_phone` | Spouse Phone | string | |
| `email` | Email | string | |
| `address` | Address | string | |
| `city` | City | string | |
| `state` | State | string | Normalized to 2-letter code |
| `zip_code` | ZIP Code | string | Zero-padded to 5 digits |
| `birth_year` | Birth Year | int | 2-digit normalized (65→1965) |
| `dob` | DOB (Full Date) | string | Flexible date parsing |
| `lead_source` | Lead Source | string | Usually auto-set from vendor/tier |
| `lead_type` | Lead Type | string | From metadata |
| `lead_age_bucket` | Lead Age Bucket | string | From metadata (per-row override) |
| `lender` | Lender | string | |
| `loan_amount` | Loan Amount | string | |
| `mail_date` | Mail Date | string | Flexible date parsing |
| `lpd` | Lead Purchase Date | string | Flexible date parsing |
| `notes` | Notes | string | |
| `gender` | Gender | string | Normalized: m/male→M, f/female→F |
| `best_time_to_call` | Best Time to Call | string | |
| `tobacco` | Tobacco? | bool | CSV string normalized |
| `medical` | Medical Issues? | bool | CSV string normalized |
| `spanish` | Spanish? | bool | CSV string normalized |

#### Batch Metadata Fields (from wizard, not CSV columns)

| Field | Applied When |
|---|---|
| `vendor + tier` → `lead_source` | When row has no `lead_source` column |
| `leadType` → `lead_type` | When row has no `lead_type` column |
| `leadAge` → `lead_age_bucket` | When row has no `lead_age_bucket` AND vendor needs it |
| `purchaseDate` → `mail_date` | When row has no `mail_date` column |
| `purchaseDate` → `lpd` | When row has no `lpd` column |
| `tier` → `tier` | Always applied from metadata |

### 6.2 Notion Properties Written (`_build_properties()`)

| Notion Property | Notion Type | Source Field | Notes |
|---|---|---|---|
| `Name` | title | `first_name + last_name` | Concatenated full name |
| `Mobile Phone` | phone_number | `phone` | Primary phone |
| `Email` | email | `email` | |
| `Lead Status` | status | `segment` (derived) | Default: "No Contact" |
| `Address` | rich_text | `address` | |
| `City` | rich_text | `city` | |
| `ZIP Code` | rich_text | `zip_code` | Zero-padded to 5 digits |
| `State` | select | `state` | Normalized to 2-letter code |
| `Age` | number | Calculated | `current_year - birth_year` |
| `LAge` | select | Calculated | From `lage_months` → bracket label |
| `Lead Type` | select | `lead_type` | |
| `Lead Source` | select | `lead_source` | "Vendor / Tier" format |
| `Mortgage Sale Date` | date | `mail_date` | Flexible parsed to YYYY-MM-DD |
| `Aggregate Comments` | rich_text | `ghl_contact_id + notes` | "GHL:{id} \| {notes}" format. Merged, not overwritten. |
| `Tier` | select | `tier` | |
| `LPD` | date | `lpd` | Flexible parsed to YYYY-MM-DD |
| `Call In Date` | date | Today's date | **Create-only** (not overwritten on update) |
| `Best Time to Call` | rich_text | `best_time_to_call` | |
| `Gender` | rich_text | `gender` | Normalized: M/F |
| `DOB` | date | `dob` | Flexible parsed to YYYY-MM-DD |
| `Home Phone` | phone_number | `home_phone` | Only written if truthy |
| `Spouse Cell` | phone_number | `spouse_phone` | Only written if truthy |
| `Lender` | rich_text | `lender` | |
| `Loan Amount` | rich_text | `loan_amount` | |
| `Tobacco?` | checkbox | `tobacco` | |
| `Medical Issues?` | checkbox | `medical` | |
| `Spanish?` | checkbox | `spanish` | |

### 6.3 GHL Fields Written (`upsert_contact()`)

| GHL Field | Source | Notes |
|---|---|---|
| `firstName` | `first_name` | |
| `lastName` | `last_name` | |
| `phone` | `phone` | E.164 normalized. Split if contains `/` delimiters. |
| `email` | `email` | |
| `address1` | `address` | |
| `city` | `city` | |
| `state` | `state` | |
| `postalCode` | `zip_code` | |
| `timezone` | Derived | From ZIP → timezone CSV lookup, falls back to state → timezone |
| `source` | `lead_source` | |
| `additionalPhones` | Various | Secondary phone, home_phone, spouse_phone as typed entries |
| **Custom Fields:** | | |
| `ZCmpWQ9KOdacOV2VZ4pn` | `lender` | Lender custom field |
| `haycapFYMCnJEFovornG` | `loan_amount` | Loan Amount custom field |
| `1MKVvQCPMsAaDb8aL5vi` | `spouse_phone` | Spouse Cell custom field |
| `za04O6KtX9Sg3yn8csZi` | `home_phone` | Home Phone custom field |
| **Tags (merged):** | | |
| `imported-MM/DD/YY` | Generated | Import date tag |
| `test-import` | Only in test mode | |

**Tag merge logic:** Read existing tags → remove old `imported-*` tags → add new import date tag → preserve all other existing tags.

**GHL Opportunity:** Created after contact upsert.
- Pipeline: MTG Leads (or first available)
- Stage: "New Lead"
- Name: `"{first_name} {last_name} — {lead_source}"`

### 6.4 Quo/OpenPhone Fields Written (`sync_contact()`)

| Quo Field | Source | Notes |
|---|---|---|
| `externalId` | `phone` (E.164) | Used as dedup key |
| `defaultFields.firstName` | `first_name` | |
| `defaultFields.lastName` | `last_name` | |
| `defaultFields.phoneNumbers` | `phone`, `home_phone` | Array: [{name: "Mobile", value: E.164}, {name: "Home", value: E.164}] |
| `defaultFields.emails` | `email` | Array: [{name: "Primary", value: email}] |
| **Custom Fields:** | | |
| `690bbacefd425c5afcd20b24` | `state` | State |
| `690bbaeffd425c5afcd20b2e` | `lender` | Lender |
| `690bbaf5fd425c5afcd20b37` | Composite | "address, city, state, zip" concatenated |

**Quo flow:** GET `/v1/contacts?externalIds=[phone]` → if exists, PATCH → if not, POST.

### 6.5 Full COLUMN_ALIASES Map

```js
// ── Names ──
'full name' → 'full_name'     'fullname' → 'full_name'
'name' → 'full_name'          'borrowername' → 'full_name'
'clientname' → 'full_name'    'applicantname' → 'full_name'
'primaryname' → 'full_name'
'first name' → 'first_name'   'firstname' → 'first_name'
'fname' → 'first_name'        'first' → 'first_name'
'borrowerfirstname' → 'first_name'  'applicantfirstname' → 'first_name'
'clientfirstname' → 'first_name'    'primaryfirstname' → 'first_name'
'last name' → 'last_name'     'lastname' → 'last_name'
'lname' → 'last_name'         'last' → 'last_name'
'borrowerlastname' → 'last_name'    'applicantlastname' → 'last_name'
'clientlastname' → 'last_name'      'primarylastname' → 'last_name'

// ── Phone (primary → 'phone') ──
'phone' → 'phone'             'phone1' → 'phone'
'primaryphone' → 'phone'      'cell' → 'phone'
'cell phone' → 'phone'        'cellphone' → 'phone'
'mobile' → 'phone'            'mphone' → 'phone'
'mobile phone' → 'phone'      'mobilephone' → 'phone'
'mobile_phone' → 'phone'
// NOTE: 'mobile phone' maps to primary 'phone', NOT mobile_phone,
// because most vendor files label their only phone as "Mobile Phone"

// ── Phone (secondary) ──
'home phone' → 'home_phone'   'home_phone' → 'home_phone'
'homephone' → 'home_phone'    'landline' → 'home_phone'
'recentlandline1' → 'home_phone'  'phone2' → 'home_phone'
'secondaryphone' → 'home_phone'   'hphone' → 'home_phone'
'spouse phone' → 'spouse_phone'    'spouse_phone' → 'spouse_phone'
'spousephone' → 'spouse_phone'     'spouse cell' → 'spouse_phone'

// ── Email ──
'email' → 'email'             'e-mail' → 'email'
'emailaddress' → 'email'

// ── Address ──
'address' → 'address'         'street' → 'address'
'street address' → 'address'  'streetaddress' → 'address'
'addr' → 'address'
'city' → 'city'               'town' → 'city'
'state' → 'state'             'st' → 'state'
'zip' → 'zip_code'            'zip_code' → 'zip_code'
'zipcode' → 'zip_code'        'zip code' → 'zip_code'
'zip_plus_four' → 'zip_code'  'postal' → 'zip_code'
'postalcode' → 'zip_code'

// ── DOB / Age ──
'dob' → 'dob'                 'date of birth' → 'dob'
'dateofbirth' → 'dob'         'birthdate' → 'dob'
'birth_date' → 'dob'          'birth date' → 'dob'
'birth year' → 'birth_year'   'birth_year' → 'birth_year'
'birthyear' → 'birth_year'    'age' → 'birth_year'
'borrowerage' → 'birth_year'

// ── Lead metadata ──
'source' → 'lead_source'      'lead source' → 'lead_source'
'lead_source' → 'lead_source' 'vendor' → 'lead_source'
'type' → 'lead_type'          'lead type' → 'lead_type'
'lead_type' → 'lead_type'
'lead age' → 'lead_age_bucket'     'lead_age' → 'lead_age_bucket'
'lead_age_bucket' → 'lead_age_bucket'

// ── Money / Lender ──
'lender' → 'lender'           'mortgage company' → 'lender'
'bank' → 'lender'             'servicer' → 'lender'
'loan amount' → 'loan_amount' 'loan_amount' → 'loan_amount'
'loanamount' → 'loan_amount'  'mtg' → 'loan_amount'
'mortgageamount' → 'loan_amount'   'mortageamount' → 'loan_amount'
'mortgage' → 'loan_amount'
'mail date' → 'mail_date'     'mail_date' → 'mail_date'
'maildate' → 'mail_date'

// ── Notes / Best Time ──
'notes' → 'notes'             'note' → 'notes'
'best time to call' → 'best_time_to_call'
'besttimetocall' → 'best_time_to_call'
'besttime' → 'best_time_to_call'   'best_time' → 'best_time_to_call'
'comment' → 'best_time_to_call'    'comments' → 'best_time_to_call'

// ── LPD ──
'lpd' → 'lpd'                 'lead purchase date' → 'lpd'
'purchasedate' → 'lpd'

// ── Flags ──
'tobacco' → 'tobacco'         'tobacco?' → 'tobacco'
'tobaccouse' → 'tobacco'      'smoker' → 'tobacco'
'borrowertobaccouse' → 'tobacco'
'medical' → 'medical'         'medical issues' → 'medical'
'medicalissues' → 'medical'   'medical issues?' → 'medical'
'borrowermedicalissues' → 'medical'  'preexistingconditions' → 'medical'
'spanish' → 'spanish'         'spanish?' → 'spanish'

// ── Gender ──
'gender' → 'gender'           'sex' → 'gender'
'genderidentity' → 'gender'   'gender_identity' → 'gender'
```

---

## 7. Error Handling & Rate Limiting

### 7.1 Notion Rate Limiting (Already Implemented)

```python
# _notion_post_with_retry() in services/notion.py
# 3 attempts, respects Retry-After header (default 1s backoff)
for attempt in range(3):
    resp = await client.post(url, ...)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", "1"))
        await asyncio.sleep(retry_after)
        continue
    return resp
```

### 7.2 GHL Rate Limiting (Already Implemented)

```python
# In bulk_import_leads() — 100ms delay between leads
if not req.dry_run and idx < len(req.leads) - 1:
    await asyncio.sleep(0.1)
```

### 7.3 Quo Rate Limiting (Already Implemented)

```python
# In sync_contact() — 200ms delay between API calls
RATE_LIMIT_DELAY = 0.2
await asyncio.sleep(RATE_LIMIT_DELAY)
```

### 7.4 Frontend Batch Rate Limiting (Already Implemented)

```js
// 100ms delay between batch POSTs (50 leads per batch)
if (i + BS < leads.length) await new Promise(r => setTimeout(r, 100))
```

### 7.5 Per-Row Error Capture

Backend already captures per-row errors with index + error message + lead name:

```python
BulkImportError(index=idx, error=str(exc), lead_name=f"{first_name} {last_name}")
```

Frontend displays these in the results step with row numbers. For multi-file, prefix with filename:
```
cheryl-t3-aged.csv — Row 47 (Jane Doe): Notion write failed: 429 rate limit exceeded
```

### 7.6 Dropped Rows

Frontend `buildLeads()` tracks `droppedCount` — rows missing required fields (first_name, last_name, phone). These are counted and displayed separately from errors.

### 7.7 Frontend Error Recovery

If bulk endpoint returns non-200, fall back to individual `/api/leads/capture` calls:
```js
// Fallback: try individual
for (const l of batch) {
  try {
    const r = await fetch('/api/leads/capture', { method: 'POST', headers, body: JSON.stringify(l) })
    if (r.ok) created++; else failed++
  } catch { failed++ }
}
```

### 7.8 Retry Failed

After import completes, if any rows failed, show "Retry N Failed" button. This re-extracts the failed rows by index and re-submits them. For multi-file, retry should be per-file.

---

## 8. Edge Cases & Normalizations

### 8.1 Full Name Splitting

When CSV has a "Name" / "Full Name" column but no separate First/Last:

```js
// In buildLeads() — already implemented
if (!lead.first_name && !lead.last_name && lead.full_name) {
  const parts = String(lead.full_name).trim().split(/\s+/)
  lead.first_name = parts[0] || ''
  lead.last_name = parts.slice(1).join(' ') || parts[0] || ''
  delete lead.full_name
}
```

Edge cases:
- `"John"` → first: "John", last: "John" (single name duplicated)
- `"John Michael Smith"` → first: "John", last: "Michael Smith"
- `"Mary Jane Watson-Parker"` → first: "Mary", last: "Jane Watson-Parker"

### 8.2 Two-Digit Birth Year Normalization

```js
// In buildLeads() — already implemented
if (lead.birth_year) {
  let yr = parseInt(lead.birth_year, 10)
  if (!isNaN(yr)) {
    if (yr >= 0 && yr <= 99) yr += yr >= 0 && yr <= 24 ? 2000 : 1900
    // 65 → 1965, 24 → 2024, 25 → 1925
    lead.birth_year = yr
  } else {
    lead.birth_year = undefined  // non-numeric → drop
  }
}
```

Backend also validates: `birth_year >= 1900` and `<= current year`.

### 8.3 State Normalization (Full Name → 2-Letter)

```python
# In _build_properties() — services/notion.py
_state_map = {
    "arizona": "AZ", "california": "CA", "pennsylvania": "PA", "maine": "ME",
    "new york": "NY", "texas": "TX", "florida": "FL", "ohio": "OH",
    "illinois": "IL", "georgia": "GA", "michigan": "MI", "washington": "WA",
    "oregon": "OR", "colorado": "CO", "nevada": "NV", "utah": "UT",
    "new mexico": "NM", "idaho": "ID", "montana": "MT", "wyoming": "WY",
    "north carolina": "NC", "south carolina": "SC", "alabama": "AL",
    "mississippi": "MS", "louisiana": "LA", "tennessee": "TN", "kentucky": "KY",
    "indiana": "IN", "iowa": "IA", "minnesota": "MN", "wisconsin": "WI",
    "missouri": "MO", "kansas": "KS", "oklahoma": "OK", "virginia": "VA",
    "west virginia": "WV", "maryland": "MD", "district of columbia": "DC",
    "dc": "DC", "delaware": "DE", "new jersey": "NJ", "connecticut": "CT",
    "rhode island": "RI", "massachusetts": "MA", "vermont": "VT",
    "new hampshire": "NH", "alaska": "AK", "hawaii": "HI", "arkansas": "AR",
    "nebraska": "NE", "south dakota": "SD", "north dakota": "ND",
}
# Fallback: take first 2 chars uppercase
state_norm = _state_map.get(_state_raw.lower(), _state_raw.upper()[:2])
```

### 8.4 ZIP Leading-Zero Padding

```python
# In _build_properties() — services/notion.py
_zip_digits = re.sub(r"\D", "", str(lead["zip_code"]))[:5]  # strip non-digits, max 5
_zip_norm = _zip_digits.zfill(5) if 1 <= len(_zip_digits) <= 5 else _zip_digits
# "4101" → "04101" (Maine), "85001" → "85001", "85001-1234" → "85001"
```

### 8.5 Date Flexible Parsing

```python
# _parse_date_flexible() in services/notion.py
# Handles: M/D/YY, M/D/YYYY, YYYY-MM-DD, M-D-YY, M-D-YYYY, YYYY/MM/DD
# All output as YYYY-MM-DD for Notion
formats = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y/%m/%d"]
```

Applied to: `mail_date`, `lpd`, `dob`.

### 8.6 Gender Normalization

```python
# In _build_properties() — services/notion.py
_g = str(lead["gender"]).strip().lower()
gender_norm = "M" if _g in {"m", "male", "man"} else "F" if _g in {"f", "female", "woman"} else str(lead["gender"]).strip()
```

### 8.7 Boolean Normalization (CSV Strings → Bool)

```js
// In buildLeads() — leadImportUtils.js
if (['tobacco', 'medical', 'spanish'].includes(field)) {
  lead[field] = ['true','1','yes','y','x','si','sí'].includes(String(row[i]).trim().toLowerCase())
}
```

### 8.8 Phone E.164 Normalization

```python
# normalize_phone() in services/ghl.py (used by GHL)
digits = re.sub(r"[^\d]", "", raw.strip())
if len(digits) == 11 and digits.startswith("1"): return f"+{digits}"
if len(digits) == 10: return f"+1{digits}"
if len(digits) >= 10: return f"+{digits}"
return ""  # too short

# _to_e164() in services/quo.py (used by Quo)
cleaned = "".join(c for c in str(phone) if c.isdigit())
if cleaned and not cleaned.startswith("1"): cleaned = "1" + cleaned
if len(cleaned) == 11: cleaned = "+" + cleaned
```

### 8.9 Phone Splitting (Multi-Number Fields)

```python
# split_phone_field() in services/ghl.py
# Handles: "5555555555/4443331234" → ["+15555555555", "+14443331234"]
parts = re.split(r"[/,;]+", raw)
```

### 8.10 Phone Fallback

```js
// In buildLeads() — leadImportUtils.js
if (!lead.phone && lead.mobile_phone) lead.phone = lead.mobile_phone
if (!lead.phone && lead.home_phone) lead.phone = lead.home_phone
```

---

## 9. UI/UX Design Spec

### 9.1 Design System (Existing — Do Not Change)

- **Fonts:** Space Grotesk (display), JetBrains Mono (data/mono)
- **Colors:** oklch color system (dark theme only)
  - `--bg: oklch(8% 0.005 240)` — deepest background
  - `--surface: oklch(12% 0.008 240)` — card/section background
  - `--surface-hover: oklch(14% 0.008 240)` — hover state
  - `--border: oklch(20% 0.01 240)` — borders
  - `--text: oklch(92% 0.005 240)` — primary text
  - `--text-muted: oklch(55% 0.008 240)` — secondary text
  - `--accent: oklch(78% 0.15 85)` — gold/amber accent
  - `--green: oklch(72% 0.18 145)` — success
  - `--amber: oklch(75% 0.15 75)` — warning
  - `--red: oklch(62% 0.2 25)` — error
- **Components:** Use existing CSS classes: `.section`, `.btn`, `.btn-primary`, `.form-input`, `.form-label`, `.badge`, `.results-table`, `.progress-bar-container`, `.progress-bar`
- **No external UI libraries.** Inline styles or CSS classes only.
- **Mobile responsive.** Follow existing breakpoints (768px, 480px).

### 9.2 New Wizard Flow (Steps)

```
Step 1: ADD FILES
  - Drop zone for multiple files
  - File queue table with per-file metadata
  - "Add More Files" button
  - Each file shows: filename, row count, vendor/tier (editable), status

Step 2: MAP COLUMNS (per-file, if needed)
  - Triggered by clicking a file in the queue OR automatically for each unmapped file
  - Clean 2-column table with sample data
  - Auto-mapped columns highlighted green
  - Required fields validation bar at top
  - "Apply to All Similar" option if multiple files have same headers

Step 3: REVIEW & CONFIRM
  - Grand summary: total files, total leads, dropped count
  - Per-file breakdown table
  - Dry run / test mode toggles
  - "Import All" button

Step 4: IMPORTING
  - Per-file progress: "Importing file 2 of 3: cheryl-t3-aged.csv (47/89)"
  - Overall progress bar
  - Real-time file status updates in queue table

Step 5: RESULTS
  - Grand total summary
  - Per-file breakdown with expand/collapse for error details
  - Retry button for failed rows (per-file)
  - "Import More" to restart
```

### 9.3 Step Indicator

Reuse existing `.wizard-step-indicator` class. Update `STEP_LABELS`:

```js
STEP_LABELS = {
  files: 'Add Files',
  mapping: 'Map Columns',
  review: 'Review',
  importing: 'Importing',
  results: 'Results',
}
```

### 9.4 Dry Run & Test Mode Toggles

Keep existing toggle buttons at the top of the wizard (above step indicator). Same styling, same behavior. They apply globally to all files in the batch.

### 9.5 Google Sheets Source

Keep existing Google Sheets import option. When sheet data is fetched, treat it as a single "file" entry in the file queue with the sheet title as filename.

---

## 10. File Structure

### 10.1 Files to Modify

| File | Changes |
|---|---|
| `frontend/src/components/LeadImport.jsx` | **Full rewrite** — multi-file wizard |
| `frontend/src/utils/leadImportUtils.js` | Add `STEP_LABELS` update. No other changes needed — all utils are reusable. |
| `frontend/src/index.css` | Add new CSS classes for file queue table, mapping table enhancements |

### 10.2 Files NOT to Modify

| File | Reason |
|---|---|
| `routers/leads.py` | Backend endpoint already handles everything correctly |
| `services/notion.py` | All field writes, normalization, rate limiting already implemented |
| `services/ghl.py` | Contact upsert, tag merge, phone normalization already implemented |
| `services/quo.py` | Contact sync already implemented |
| `frontend/src/App.jsx` | No routing/layout changes needed |

### 10.3 New Component (Optional)

Consider extracting into sub-components for maintainability:

```
LeadImport.jsx            — Main wizard container + state management
├── FileQueue.jsx          — File queue table with metadata editing
├── ColumnMapper.jsx       — Clean column mapping UI for a single file
├── ImportProgress.jsx     — Per-file and overall progress display
└── ImportResults.jsx      — Grand summary + per-file breakdown
```

Builder decides whether to extract or keep in single file.

---

## 11. Backend Changes Required

### 11.1 None Required for Core Flow

The existing `POST /api/leads/bulk` endpoint handles everything:
- Accepts `leads[]`, `dry_run`, `test_mode`
- Processes Notion → GHL → Quo pipeline per row
- Returns `created`, `updated`, `failed`, `quo_synced`, `errors[]`, `ghl_warnings[]`

### 11.2 Potential Enhancement (Low Priority)

If the Builder wants to add file-level tracking, consider adding a `file_name` field to the request so the backend can include it in error messages. But this is purely cosmetic — the frontend can prefix errors with the filename itself.

---

## Appendix A: Vendor Filename Detection Patterns

```js
// autoDetectVendor() in leadImportUtils.js
// Input: filename string (lowercased)
// Patterns:
//   "hof" → HOFLeads, checks for "gold"/"t2" → Gold, "silver"/"t3" → Silver, else Diamond
//   "proven" → Proven Leads, N/A tier
//   "aria" → Aria Leads, Gold tier
//   "milmo" → MilMo, Gold tier
//   "final expense" or "_fe_" → Final Expense lead type
//   "annuity" → Annuity lead type
//   "iul" → IUL lead type
//   Default: HOFLeads / Diamond / Mortgage Protection
```

**Builder should add:** `"cheryl"` pattern → Cheryl vendor. Currently not detected.

## Appendix B: LAge Bracket Calculation

```python
# In services/notion.py
LAGE_BRACKETS = [
    (0,  7,    "3+ Month"),   # 0–6 months since mail date
    (7,  13,   "7-12M"),
    (13, 25,   "13–24M"),
    (25, 37,   "25–36M"),
    (37, 49,   "37–48M"),
    (49, 61,   "49–60M"),
    (61, 9999, "60+M"),
]
# calculate_lage() returns months since mail_date
# _lage_select() converts months → bracket label
```

## Appendix C: Derived Fields

| Field | Calculation | When |
|---|---|---|
| `age` | `current_year - birth_year` | When `birth_year` is provided |
| `lage_months` | Months since `mail_date` | When `mail_date` is provided |
| `LAge` (Notion select) | `lage_months` → bracket label | After lage_months calculated |
| `timezone` (GHL) | ZIP → timezone CSV lookup, fallback to state | On GHL upsert |
| `lead_source` | `"{vendor} / {tier}"` | When row has no lead_source |
| `Call In Date` | Today's date | On Notion create only |

---

*End of spec. Builder agent has everything needed to implement.*