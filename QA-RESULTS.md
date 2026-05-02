# QA Results — Lead Import Rebuild

**QA Agent:** Dolf (QA Subagent)  
**Date:** 2026-03-11  
**Build Hash:** `index-CrWsymvP.js` / `index-eZbJcYdB.css`

> **Note (2026-04-26):** Quo/OpenPhone has been removed from the import
> pipeline. The Quo-related rows below (`sync_contact()`, `quo_synced` counter,
> Quo rate limiting, Quo field parity) are historical and no longer apply.

---

## Summary: BLOCKED

## Critical Issues: 3
## Non-Critical Issues: 5

---

## Validation Matrix

| Feature | Status | Notes |
|-------------------------------|--------|-------|
| Multi-CSV batch upload | ❌ | **Single file only.** File input has no `multiple` attr. No file queue/table. No per-file state management. Spec called for multi-file batch with sequential processing. |
| Per-file metadata | ❌ | N/A — single file flow. Metadata is global, not per-file. Works correctly for single-file use case. |
| Sequential processing | ❌ | N/A — single file flow. No file queue to iterate. |
| Per-file progress + results | ⚠️ | Single file progress works (current/total with progress bar). No per-file breakdown since multi-file not implemented. |
| Clean mapping table | ✓ | 3-column layout: CSV header → arrow → dropdown. Scrollable, readable, not cramped. |
| Sample data in mapping | ❌ | **No sample data shown.** Spec called for showing first non-empty value from CSV next to each column header. Only the header name is displayed. |
| Required field highlighting | ⚠️ | Warning bar shows "Map at least First Name, Last Name, and Phone to continue" when requirements not met. But no per-row red asterisk on unmapped required fields. No red tint on required rows. |
| Auto-mapped highlighting | ⚠️ | Mapped columns get a "mapped" badge (green). But no distinct visual between auto-mapped (from aliases) vs manually-mapped. No green tint on auto-mapped rows per spec. |
| Test Mode toggle | ✓ | Present, functional. Only shows when Dry Run is OFF (correct). Clear explanation text. Blue color scheme distinguishes from Dry Run. |
| Dry Run toggle | ✓ | Present, functional. Clear amber styling when active. Explanation text accurate. |
| Full name splitting | ✓ | If CSV has `full_name` but no `first_name`/`last_name`, splits on first space. `"John Smith Jr"` → first: `"John"`, last: `"Smith Jr"`. Correct. |
| 2-digit birth year | ✓ | `65` → `1965`, `24` → `2024`, `25` → `1925`. Logic: 0-24 → +2000, 25-99 → +1900. Correct. |
| State normalization | ✓ | Full 50-state map in `_build_properties()`. "Arizona" → "AZ", "New York" → "NY", etc. Falls back to `.upper()[:2]` for unrecognized. |
| ZIP padding | ✓ | Strips non-digits, takes first 5, zero-pads with `zfill(5)`. "4101" → "04101". Correct. |
| Date parsing variants | ✓ | `_parse_date_flexible()` handles: `YYYY-MM-DD`, `M/D/YYYY`, `M/D/YY`, `M-D-YYYY`, `M-D-YY`, `YYYY/MM/DD`. 6 formats covered. |
| E.164 phone normalization | ✓ | Both GHL (`normalize_phone`) and Quo (`_to_e164`) normalize to `+1XXXXXXXXXX`. GHL also handles split phones with `/` delimiter. |
| COLUMN_ALIASES completeness | ✓ | Comprehensive coverage. 80+ aliases covering: full name variations (BorrowerName, ClientName, ApplicantName, PrimaryName), phone variations (Mobile Phone → phone primary, Home Phone → home_phone, etc.), DOB/age, address, lender, flags (tobacco/medical/spanish), gender. Notable design decision: "Mobile Phone" → primary `phone` (not `mobile_phone`) because most vendors label their only phone as "Mobile Phone". Well-documented in comments. |
| Notion field parity | ✓ | `_build_properties()` writes 25+ properties including: Name, Mobile Phone, Email, Lead Status, Address, City, ZIP Code, State, Age, LAge, Lead Type, Lead Source, Mortgage Sale Date, Aggregate Comments, Tier, LPD, Call In Date (create-only), Best Time to Call, Gender (M/F normalized), DOB, Home Phone, Spouse Cell, Lender, Loan Amount, Tobacco?, Medical Issues?, Spanish?. Matches spec exactly. |
| GHL field parity | ✓ | `upsert_contact()` writes: firstName, lastName, phone (E.164), email, address1, city, state, postalCode, timezone (ZIP→tz lookup with state fallback), source, additionalPhones (home, spouse), custom fields (Lender, Loan Amount, Spouse Cell, Home Phone). Tag merge: reads existing, removes old imported-* tags, adds new date tag + test-import if test mode. Opportunity created with pipeline stage. |
| Quo field parity + customs | ✓ | `sync_contact()` writes: externalId (E.164 phone), defaultFields (firstName, lastName, phoneNumbers array, emails), customFields (State: `690bbacefd425c5afcd20b24`, Lender: `690bbaeffd425c5afcd20b2e`, Address: `690bbaf5fd425c5afcd20b37` — composite of address+city+state+zip). GET→PATCH/POST flow with 200ms rate limiting. |
| Build passes (0 errors) | ✓ | `vite build` succeeds. 719 modules transformed. Only warning: chunk size >500kB (expected for single-bundle SPA). No TypeScript/syntax errors. |

---

## Blockers (Must Fix Before Deploy)

### 1. Multi-CSV Batch Import Not Implemented ❌

**Spec requirement:** The IMPORT-SPEC.md defines a complete multi-file batch system with file queue table, per-file metadata, per-file column mapping, sequential processing, and grand total summary.

**Current state:** The component handles **one file at a time** — same as the original. The file input is `<input type="file">` (no `multiple`), state is flat (single `headers`, `parsedRows`, `columnMap`, `vendor`, `tier`, etc.), and there's no file queue array.

**Impact:** This was the #1 feature in the spec. Without it, importing 3 CSV batches requires running the wizard 3 times.

**Fix required:** Either:
- (a) Implement full multi-file per the spec (significant refactor — new state shape, file queue component, per-file mapping step)
- (b) Explicitly downscope and document that multi-file is deferred to a future sprint

### 2. No Sample Data in Column Mapping ❌

**Spec requirement (Section 3.5):** Show the first non-empty value from parsed rows next to each CSV column in the mapping table. Example: `First Name | "John" | [First Name ▾]`

**Current state:** The mapping UI shows `CSV Header → Dropdown` but no sample values. Users must guess what data is in ambiguous columns (e.g., "MTG" — is it loan amount or mortgage company?).

**Fix required:** Add a sample data column. Implementation is ~10 lines:
```jsx
const sampleValue = parsedRows.find(row => row[headers.indexOf(h)])?.[headers.indexOf(h)] || "—"
```

### 3. `full_name` Missing from LEAD_FIELDS Dropdown ❌

**Issue:** If a CSV column header doesn't match any COLUMN_ALIAS but contains a full name, users cannot manually map it to "Full Name" because `full_name` is not in the `LEAD_FIELDS` array (the dropdown options). It only works via auto-mapping from aliases.

**Fix required:** Add `{ value: 'full_name', label: 'Full Name' }` to the LEAD_FIELDS array.

---

## Non-Critical Issues (Should Fix)

### 4. Duplicate LEAD_FIELDS Entries ⚠️

`home_phone` (label: "Home Phone") and `spouse_phone` (label: "Spouse Phone") each appear twice in the LEAD_FIELDS array. This causes duplicate options in the mapping dropdown. Non-breaking but sloppy.

### 5. No Visual Distinction for Auto-Mapped vs Manually-Mapped ⚠️

Spec called for green tint on auto-mapped rows and amber tint on manually-mapped rows. Current UI shows the same "mapped" badge for both. Low priority but would improve UX.

### 6. No Red Asterisk/Tint on Unmapped Required Fields ⚠️

Spec called for red asterisk indicators and red background tint on required fields that haven't been mapped. Current UI has a warning text bar at the top but no per-field visual indicator. The warning text works but the per-field UX would be cleaner.

### 7. No Sorting (Mapped Columns to Top) ⚠️

Spec Section 3.6 called for mapped columns sorted to top, unmapped to bottom. Current UI preserves original CSV column order. Minor UX improvement.

### 8. Mapping Row Could Show "— skip —" Label More Clearly ⚠️

The dropdown shows `— skip —` as an option (value=""), which works correctly. The `<option value="">— skip —</option>` pattern is fine.

---

## What Works Well (No Issues Found)

1. **Backend is solid.** `BulkImportRequest` with `dry_run` + `test_mode`, `BulkImportResponse` with `quo_synced` — all present and correct.
2. **3-system write pipeline** (Notion → GHL → Quo) with correct failure handling: Notion failure skips row, GHL failure logs warning but counts as success, Quo failure is non-fatal.
3. **Test mode** correctly overrides tier to "TEST", prefixes lead_source with "[TEST]", adds "test-import" GHL tag.
4. **Dry run** correctly validates without any external API calls.
5. **Edge case handling** is comprehensive: full name splitting, 2-digit birth year, state normalization (50 states), ZIP padding, flexible date parsing (6 formats), boolean normalization, phone E.164 conversion.
6. **COLUMN_ALIASES** coverage is excellent — 80+ aliases with thoughtful design decisions (e.g., "Mobile Phone" → primary phone with inline comment explaining why).
7. **Rate limiting** at all three layers: Notion (retry with backoff), GHL (100ms between leads), Quo (200ms between calls), Frontend (100ms between batch POSTs).
8. **GHL tag merge logic** is read-then-merge (not overwrite) — preserves existing tags while adding import date tag.
9. **IMPORT-SPEC.md** exists and is comprehensive (550+ lines covering all design decisions, field maps, alias tables, error handling).
10. **Code comments** in both LeadImport.jsx (32 comments) and leadImportUtils.js (30 comments) explain key decisions including BUG fix references.

---

## Recommendations

1. **Prioritize blockers #1-#3** — particularly #2 (sample data) and #3 (full_name in dropdown) which are quick wins.
2. **Multi-file (#1) could be deferred** if Seb confirms single-file workflow is acceptable for now. The single-file flow works correctly — it's just not the multi-file spec.
3. **Remove duplicate LEAD_FIELDS entries** — quick cleanup.
4. **Consider adding `full_name`** to LEAD_FIELDS even though auto-mapping handles most cases. Edge case: a column named "Person" wouldn't auto-map but clearly should map to full_name.

---

*QA completed 2026-03-11 19:05 MST*
