"""Pure classification, normalization, matching, and reporting helpers for the
FalconConnect old lead hygiene MVP.

This module has no side effects and no I/O against Close, GHL, or Notion. It
is safe to import in tests, scripts, and FastAPI handlers. All API access is
the responsibility of services.lead_hygiene_collect.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────────────────────────────

_DUMMY_EMAIL_LOCAL = {"noemail", "no-email", "none", "n/a", "na"}
_DUMMY_EMAIL_DOMAINS = {"none.com"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_NAME_DECORATION_RE = re.compile(
    r"\s*\(.*?\)|\s*-\s*(DNC|DECEASED|DO NOT CONTACT).*",
    re.IGNORECASE,
)


def normalize_phone(raw: Any) -> str:
    """Return a phone in +1XXXXXXXXXX form or "" if it can't be normalised."""
    if raw is None:
        return ""
    raw_str = str(raw).strip()
    if not raw_str or raw_str.lower() in {"none", "null", "n/a", "na"}:
        return ""
    digits = re.sub(r"\D", "", raw_str)
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) > 11:
        return f"+{digits}"
    return ""


def normalize_email(raw: Any) -> str:
    """Lowercase + strip an email. Returns "" for dummy/placeholder addresses."""
    if raw is None:
        return ""
    val = str(raw).strip().lower()
    if not val:
        return ""
    if not _EMAIL_RE.match(val):
        return ""
    local, _, domain = val.partition("@")
    if local in _DUMMY_EMAIL_LOCAL:
        return ""
    if domain in _DUMMY_EMAIL_DOMAINS:
        return ""
    if local.startswith("noemail") or local.startswith("no-email"):
        return ""
    return val


def normalize_name(raw: Any) -> str:
    """Title-case + collapse whitespace + strip parenthetical/DNC decoration."""
    if raw is None:
        return ""
    val = str(raw).strip()
    if not val:
        return ""
    val = _NAME_DECORATION_RE.sub("", val)
    val = re.sub(r"\s+", " ", val).strip()
    if not val:
        return ""
    # Preserve hyphens in last names while title-casing each token.
    parts = []
    for token in val.split(" "):
        sub = "-".join(p.capitalize() for p in token.split("-"))
        parts.append(sub)
    return " ".join(parts)


def name_parts(raw: Any) -> Tuple[str, str]:
    """Return (first_segment, last_token) from a normalised name."""
    name = normalize_name(raw)
    if not name:
        return "", ""
    tokens = name.split(" ")
    if len(tokens) == 1:
        return tokens[0], ""
    return " ".join(tokens[:-1]), tokens[-1]


# ──────────────────────────────────────────────────────────────────────
# Matching
# ──────────────────────────────────────────────────────────────────────


@dataclass
class MatchResult:
    ghl_id: Optional[str] = None
    notion_id: Optional[str] = None
    match_basis: Optional[str] = None  # "phone" | "email" | "name" | None
    ambiguous: bool = False
    warnings: List[str] = field(default_factory=list)


@dataclass
class _RecordIndex:
    """Inverted indexes from normalised phone/email/full-name to source IDs.

    Each value is a list — when length > 1 we treat the lookup as ambiguous.
    """

    ghl_by_phone: Dict[str, List[Dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    ghl_by_email: Dict[str, List[Dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    ghl_by_full_name: Dict[str, List[Dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    notion_by_phone: Dict[str, List[Dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    notion_by_email: Dict[str, List[Dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    notion_by_full_name: Dict[str, List[Dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    close_phone_counts: Counter = field(default_factory=Counter)


def _normalize_record_keys(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **rec,
        "_phones": [normalize_phone(p) for p in rec.get("phones", []) if normalize_phone(p)],
        "_emails": [normalize_email(e) for e in rec.get("emails", []) if normalize_email(e)],
        "_name": normalize_name(rec.get("name", "")),
    }


def build_record_index(
    close_records: Iterable[Dict[str, Any]],
    ghl_records: Iterable[Dict[str, Any]],
    notion_records: Iterable[Dict[str, Any]],
) -> _RecordIndex:
    idx = _RecordIndex()
    for rec in ghl_records:
        rec = _normalize_record_keys(rec)
        for phone in rec["_phones"]:
            idx.ghl_by_phone[phone].append(rec)
        for email in rec["_emails"]:
            idx.ghl_by_email[email].append(rec)
        if rec["_name"]:
            idx.ghl_by_full_name[rec["_name"].lower()].append(rec)
    for rec in notion_records:
        rec = _normalize_record_keys(rec)
        for phone in rec["_phones"]:
            idx.notion_by_phone[phone].append(rec)
        for email in rec["_emails"]:
            idx.notion_by_email[email].append(rec)
        if rec["_name"]:
            idx.notion_by_full_name[rec["_name"].lower()].append(rec)
    for rec in close_records:
        rec = _normalize_record_keys(rec)
        for phone in rec["_phones"]:
            idx.close_phone_counts[phone] += 1
    return idx


def _pick_unique(candidates: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Return (record, ambiguous). If multiple candidates → (None, True)."""
    if not candidates:
        return None, False
    if len(candidates) == 1:
        return candidates[0], False
    # Deduplicate by source_id in case the same record was indexed via multiple
    # phones/emails.
    unique = {c.get("source_id"): c for c in candidates}
    if len(unique) == 1:
        return next(iter(unique.values())), False
    return None, True


def _name_match_with_lastname_guard(
    a_name: str, b_name: str
) -> bool:
    """True only when first segment matches AND last token matches.

    Never matches on first-name only — enforces the spec rule.
    """
    a_first, a_last = name_parts(a_name)
    b_first, b_last = name_parts(b_name)
    if not a_last or not b_last:
        return False
    if a_last.lower() != b_last.lower():
        return False
    return a_first.lower() == b_first.lower()


def match_records(close_record: Dict[str, Any], index: _RecordIndex) -> MatchResult:
    """Find the best GHL + Notion match for a single Close lead."""
    rec = _normalize_record_keys(close_record)
    result = MatchResult()

    # ---- GHL match: phone, then email, then name ----
    ghl_candidates: List[Dict[str, Any]] = []
    basis: Optional[str] = None
    for phone in rec["_phones"]:
        ghl_candidates.extend(index.ghl_by_phone.get(phone, []))
    if ghl_candidates:
        basis = "phone"
    if not ghl_candidates:
        for email in rec["_emails"]:
            ghl_candidates.extend(index.ghl_by_email.get(email, []))
        if ghl_candidates:
            basis = "email"
    if not ghl_candidates and rec["_name"]:
        for cand in index.ghl_by_full_name.get(rec["_name"].lower(), []):
            if _name_match_with_lastname_guard(rec["_name"], cand["_name"]):
                ghl_candidates.append(cand)
        if ghl_candidates:
            basis = "name"

    picked, ambiguous = _pick_unique(ghl_candidates)
    if ambiguous:
        result.ambiguous = True
    elif picked is not None:
        result.ghl_id = picked.get("source_id")
        result.match_basis = basis
        if rec["_name"] and picked["_name"] and not _name_match_with_lastname_guard(
            rec["_name"], picked["_name"]
        ):
            result.warnings.append("name_mismatch")

    # ---- Notion match: phone, then email, then name ----
    notion_candidates: List[Dict[str, Any]] = []
    notion_basis: Optional[str] = None
    for phone in rec["_phones"]:
        notion_candidates.extend(index.notion_by_phone.get(phone, []))
    if notion_candidates:
        notion_basis = "phone"
    if not notion_candidates:
        for email in rec["_emails"]:
            notion_candidates.extend(index.notion_by_email.get(email, []))
        if notion_candidates:
            notion_basis = "email"
    if not notion_candidates and rec["_name"]:
        for cand in index.notion_by_full_name.get(rec["_name"].lower(), []):
            if _name_match_with_lastname_guard(rec["_name"], cand["_name"]):
                notion_candidates.append(cand)
        if notion_candidates:
            notion_basis = "name"

    n_picked, n_ambiguous = _pick_unique(notion_candidates)
    if n_ambiguous:
        result.ambiguous = True
    elif n_picked is not None:
        result.notion_id = n_picked.get("source_id")
        # Use the broader basis when we don't already have one from GHL.
        if not result.match_basis:
            result.match_basis = notion_basis

    return result


# ──────────────────────────────────────────────────────────────────────
# Classification
# ──────────────────────────────────────────────────────────────────────


# Hard-stop detection.
#
# Phrase patterns use word boundaries so "stopped" / "weekend" / "legend"
# never match "stop" / "end". The patterns scan ANY activity body — notes,
# tasks, custom activities, email body/subject — regardless of direction,
# because those bodies are agent-authored records of what the lead said.
# Outbound SMS + outbound email bodies are skipped entirely (those are our
# own template copy, frequently containing "Reply STOP to opt out").
#
# Priority on multiple matches: dnc > stop > opt_out.

_DNC_RES = [
    re.compile(r"\bdo\s+not\s+(?:call|contact|text|message|email|reach)\b", re.IGNORECASE),
    re.compile(r"\btake\s+me\s+off\b", re.IGNORECASE),
    re.compile(r"\bremove\s+me\b", re.IGNORECASE),
    re.compile(r"\bnever\s+(?:call|text|message|contact|reach)\b", re.IGNORECASE),
    re.compile(r"\bdnc\b", re.IGNORECASE),
]
_STOP_RES = [
    re.compile(r"\bstop\s+(?:texting|calling|messaging|emailing|contacting)\b", re.IGNORECASE),
    re.compile(r"\bstop\s+reaching\s+out\b", re.IGNORECASE),
    re.compile(r"\blose\s+my\s+number\b", re.IGNORECASE),
]
_OPT_OUT_RES = [
    re.compile(r"\bunsubscribe\b", re.IGNORECASE),
    re.compile(r"\bopt[\s\-]?out\b", re.IGNORECASE),
    re.compile(r"\bno\s+more\s+(?:texts?|calls?|emails?|messages?)\b", re.IGNORECASE),
]
# Bare SMS opt-out keyword (the literal carrier keyword). Only valid on
# inbound SMS — outbound templates may use these words as instructions.
_SMS_KEYWORD_RE = re.compile(
    r"^\s*(stop|stopall|quit|end|cancel|unsubscribe)\b[\s\.!]*$",
    re.IGNORECASE,
)
# Activity body fields that may carry agent-readable text across Close
# activity types: note, sms, email, call, task_completed, custom.
_BODY_FIELDS = ("text", "note", "body", "body_text", "task_text", "subject")
# Rank for resolving conflicting hard-stop signals.
_HARD_STOP_RANK = {None: 0, "opt_out": 1, "stop": 2, "dnc": 3}

_GHL_AUTOMATED_TAGS = {
    "rvm-complete", "rvm-pending", "rvm-staging", "rvm-failed",
    "r0-complete", "r1-complete", "r2-complete", "r3-complete",
}
_GHL_RVM_TAGS = {"rvm-complete", "rvm-pending", "rvm-staging", "rvm-failed"}

CADENCE_AUTO_VALUES = {
    "1. r0-pending", "2. r1-calling", "3. r1-done", "4. r2-calling",
    "5. r2-done", "6. r3-calling", "7. r3-done",
}


@dataclass
class ClassificationContext:
    close_lead_id: str
    ghl_contact_id: Optional[str]
    notion_page_id: Optional[str]
    lead_name: str
    phones: List[str]
    emails: List[str]
    close_status: Optional[str]
    cadence_stage: Optional[str]
    ghl_tags: List[str]
    notion_status: Optional[str]
    notion_opportunity_stage: Optional[str]
    close_activities: List[Dict[str, Any]]
    notion_body: str
    ambiguous_match: bool
    duplicate_phone: bool
    now: datetime
    recent_window_days: int = 30


@dataclass
class ClassificationResult:
    recommended_bucket: str
    risk_flags: List[str]
    recommended_ghl_tags: List[str]
    recommended_close_update: Optional[str]
    confidence: float
    reason: str
    last_outbound_touch: Optional[str] = None
    last_inbound_touch: Optional[str] = None
    last_automation_touch: Optional[str] = None
    last_appointment: Optional[str] = None
    activity_summary: str = ""


def _extract_activity_body(a: Dict[str, Any]) -> str:
    """Concatenate every text-bearing field on a Close activity.

    Different activity types put their body in different keys:
      - note: `note`
      - sms: `text`
      - email: `body_text` + `subject`
      - call: `note`
      - task / task_completed: `text` and/or `task_text`
      - custom: `note`
    Concatenating with spaces is safe because we only ever pattern-match.
    """
    parts: List[str] = []
    for key in _BODY_FIELDS:
        v = a.get(key)
        if v:
            parts.append(str(v))
    return " ".join(parts).strip()


def _stronger_kind(existing: Optional[str], new: Optional[str]) -> Optional[str]:
    return new if _HARD_STOP_RANK.get(new, 0) > _HARD_STOP_RANK.get(existing, 0) else existing


def _detect_hard_stop(body: str, atype: str, direction: str) -> Optional[str]:
    """Return 'dnc' / 'stop' / 'opt_out' / None for a single text body.

    Outbound SMS and outbound email bodies are skipped — those are our own
    template copy and frequently contain phrases like "Reply STOP to opt out".
    All other bodies (notes, tasks, call notes, custom activities, Notion
    aggregate comments) are scanned regardless of direction.
    """
    if not body:
        return None
    if direction == "outbound" and atype in {"sms", "email"}:
        return None
    text = body.strip()

    # Bare SMS opt-out keyword on a line by itself.
    if atype == "sms" and direction == "inbound":
        for line in text.splitlines():
            m = _SMS_KEYWORD_RE.match(line)
            if m:
                token = m.group(1).lower()
                if token in {"unsubscribe", "cancel"}:
                    return "opt_out"
                return "stop"

    for pat in _DNC_RES:
        if pat.search(text):
            return "dnc"
    for pat in _STOP_RES:
        if pat.search(text):
            return "stop"
    for pat in _OPT_OUT_RES:
        if pat.search(text):
            return "opt_out"
    return None


def _parse_dt(s: Any) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    try:
        text = str(s).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _scan_activities(
    activities: List[Dict[str, Any]],
    now: datetime,
    window_days: int,
) -> Dict[str, Any]:
    """Walk activities once and surface every signal classification needs."""
    last_outbound: Optional[datetime] = None
    last_inbound: Optional[datetime] = None
    last_automation: Optional[datetime] = None
    last_appointment: Optional[datetime] = None
    hard_stop_kind: Optional[str] = None  # "stop" | "opt_out" | "dnc"
    inbound_response = False
    appointment_seen = False
    automation_note_seen = False

    counts = Counter()
    for a in activities:
        atype = (a.get("type") or "").lower()
        counts[atype] += 1
        direction = (a.get("direction") or "").lower()
        body = _extract_activity_body(a)
        dt = _parse_dt(a.get("date_created") or a.get("date") or a.get("created_at"))

        is_appointment = (
            atype in {"custom_activity", "appointment"}
            and "appointment" in (a.get("activity_type_name") or "").lower()
        )
        if is_appointment:
            appointment_seen = True
            if dt and (last_appointment is None or dt > last_appointment):
                last_appointment = dt

        if atype == "call":
            if direction == "outbound":
                if dt and (last_outbound is None or dt > last_outbound):
                    last_outbound = dt
            elif direction == "inbound":
                inbound_response = True
                if dt and (last_inbound is None or dt > last_inbound):
                    last_inbound = dt
        elif atype == "sms":
            if direction == "outbound":
                if dt and (last_outbound is None or dt > last_outbound):
                    last_outbound = dt
            elif direction == "inbound":
                inbound_response = True
                if dt and (last_inbound is None or dt > last_inbound):
                    last_inbound = dt

        if body:
            kind = _detect_hard_stop(body, atype, direction)
            if kind:
                hard_stop_kind = _stronger_kind(hard_stop_kind, kind)
            body_lower = body.lower()
            if any(t in body_lower for t in ("rvm fired", "rvm sent", "rvm complete",
                                            "ghl workflow", "automation fired")):
                automation_note_seen = True
                if dt and (last_automation is None or dt > last_automation):
                    last_automation = dt

    recent_outbound = (
        last_outbound is not None
        and (now - last_outbound).days <= window_days
    )

    return {
        "last_outbound": last_outbound,
        "last_inbound": last_inbound,
        "last_automation": last_automation,
        "last_appointment": last_appointment,
        "hard_stop_kind": hard_stop_kind,
        "inbound_response": inbound_response,
        "appointment_seen": appointment_seen,
        "automation_note_seen": automation_note_seen,
        "recent_outbound": recent_outbound,
        "counts": counts,
    }


def classify_lead(ctx: ClassificationContext) -> ClassificationResult:
    flags: List[str] = []
    scan = _scan_activities(ctx.close_activities, ctx.now, ctx.recent_window_days)

    # Notion aggregate comments are scanned with the same hard-stop rules.
    # The Notion body is agent-authored historical narrative, so all phrases
    # apply regardless of direction.
    if ctx.notion_body:
        notion_kind = _detect_hard_stop(ctx.notion_body, atype="notion", direction="")
        if notion_kind:
            scan["hard_stop_kind"] = _stronger_kind(scan["hard_stop_kind"], notion_kind)

    # ── Risk-flag harvesting (pure observation, no bucketing yet) ──
    status = (ctx.close_status or "").strip()
    notion_status = (ctx.notion_status or "").strip()
    notion_opp = (ctx.notion_opportunity_stage or "").strip()
    tags = {t.lower() for t in ctx.ghl_tags or []}

    if ctx.ambiguous_match:
        flags.append("ambiguous_match")
    if not ctx.phones:
        flags.append("missing_phone")
    if ctx.duplicate_phone:
        flags.append("duplicate_phone")
    if scan["hard_stop_kind"] == "stop":
        flags.append("stop_language")
    if scan["hard_stop_kind"] == "opt_out":
        flags.append("sms_opt_out")
    if scan["hard_stop_kind"] == "dnc":
        flags.append("dnc_language")
    if status.lower() in {"not interested", "not interested/lost"}:
        flags.append("not_interested_status")
    if notion_status.lower() in {"not interested/lost", "not interested"}:
        flags.append("not_interested_status")
    if status.lower() == "invalid":
        flags.append("invalid_status")
    if status.lower() == "client":
        flags.append("client_status")
    if notion_opp.lower() == "approved":
        flags.append("client_status")
    if scan["recent_outbound"]:
        flags.append("recent_outbound_touch")
    if scan["inbound_response"]:
        flags.append("inbound_response_detected")
    if scan["appointment_seen"]:
        flags.append("appointment_detected")
    if any(t in _GHL_RVM_TAGS for t in tags):
        flags.append("rvm_tag_detected")
    if any(t in _GHL_AUTOMATED_TAGS - _GHL_RVM_TAGS for t in tags) or scan["automation_note_seen"]:
        flags.append("ghl_workflow_detected")

    # ── Bucket priority (highest to lowest hard-stops first) ──
    bucket: str
    reason: str
    confidence: float
    recommended_close_update: Optional[str] = None
    recommended_tags: List[str] = []

    if scan["hard_stop_kind"]:
        bucket = "do-not-contact"
        reason = f"Hard stop detected ({scan['hard_stop_kind']}) in activity history."
        confidence = 0.95
        recommended_tags = ["do-not-contact"]
        recommended_close_update = "status=Not Interested + add note 'DNC per lead message'"
    elif "client_status" in flags:
        bucket = "client"
        reason = "Lead is an existing client/won opportunity."
        confidence = 0.95
        recommended_tags = ["client"]
    elif "invalid_status" in flags:
        bucket = "invalid"
        reason = "Close status is Invalid."
        confidence = 0.95
        recommended_tags = ["invalid"]
    elif "not_interested_status" in flags:
        bucket = "not-interested"
        reason = "Status or evidence indicates not-interested."
        confidence = 0.9
        recommended_tags = ["not-interested"]
    elif "missing_phone" in flags:
        bucket = "missing-phone"
        reason = "No usable phone number on file."
        confidence = 0.9
    elif "duplicate_phone" in flags:
        bucket = "duplicate"
        reason = "Phone number appears on multiple Close leads — needs manual dedupe."
        confidence = 0.85
    elif "ambiguous_match" in flags:
        bucket = "needs-review"
        reason = "Ambiguous cross-system match — multiple GHL or Notion candidates."
        confidence = 0.6
    elif "appointment_detected" in flags:
        bucket = "needs-review"
        reason = "Appointment history present — manual triage before automation."
        confidence = 0.7
    elif "inbound_response_detected" in flags:
        bucket = "needs-review"
        reason = "Inbound response detected — manual triage before automation."
        confidence = 0.7
    elif any(t in _GHL_AUTOMATED_TAGS for t in tags) or scan["automation_note_seen"]:
        bucket = "already-automated"
        reason = "GHL automation tag or note already on lead."
        confidence = 0.85
    elif "recent_outbound_touch" in flags:
        bucket = "recently-contacted"
        reason = f"Outbound touch within the last {ctx.recent_window_days} days."
        confidence = 0.9
    elif scan["last_outbound"] is not None and status.lower() == "contacted":
        # Conversation took place — surface for manual review before re-staging.
        bucket = "previous-outreach-detected"
        reason = "Old outbound activity on a previously-contacted lead; review before re-engaging."
        confidence = 0.75
    elif status.lower() in {"voicemail", "re-engage"} or (ctx.cadence_stage or "").lower() == "nurture":
        # Never connected (Voicemail) or nurture/re-engage — safe to stage.
        bucket = "reengage-ready"
        reason = "Old lead with no hard stop and no recent activity — safe to stage."
        confidence = 0.8
        recommended_tags = ["rvm-staging"]
    elif scan["last_outbound"] is not None:
        bucket = "previous-outreach-detected"
        reason = "Old outbound activity exists; review before re-engaging."
        confidence = 0.75
    else:
        bucket = "needs-review"
        reason = "Insufficient signal to bucket — manual review required."
        confidence = 0.4

    # Defensive: never recommend the active workflow trigger tag.
    recommended_tags = [t for t in recommended_tags if t.lower() != "rvm-pending"]

    return ClassificationResult(
        recommended_bucket=bucket,
        risk_flags=sorted(set(flags)),
        recommended_ghl_tags=recommended_tags,
        recommended_close_update=recommended_close_update,
        confidence=confidence,
        reason=reason,
        last_outbound_touch=scan["last_outbound"].isoformat() if scan["last_outbound"] else None,
        last_inbound_touch=scan["last_inbound"].isoformat() if scan["last_inbound"] else None,
        last_automation_touch=scan["last_automation"].isoformat() if scan["last_automation"] else None,
        last_appointment=scan["last_appointment"].isoformat() if scan["last_appointment"] else None,
        activity_summary=_summarise_activity(scan["counts"]),
    )


def _summarise_activity(counts: Counter) -> str:
    parts = []
    for key in ("call", "sms", "email", "note", "custom_activity"):
        parts.append(f"{counts.get(key, 0)} {key}")
    return ", ".join(parts)


# ──────────────────────────────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────────────────────────────


REPORT_COLUMNS = [
    "lead_name",
    "phone",
    "email",
    "close_lead_id",
    "ghl_contact_id",
    "notion_page_id",
    "close_status",
    "cadence_stage",
    "ghl_tags",
    "notion_status",
    "notion_opportunity_stage",
    "last_outbound_touch",
    "last_inbound_touch",
    "last_automation_touch",
    "last_appointment",
    "activity_summary",
    "risk_flags",
    "recommended_bucket",
    "recommended_ghl_tags",
    "recommended_close_update",
    "confidence",
    "reason",
]


@dataclass
class ReportRow:
    lead_name: str
    phone: str
    email: str
    close_lead_id: str
    ghl_contact_id: Optional[str]
    notion_page_id: Optional[str]
    close_status: Optional[str]
    cadence_stage: Optional[str]
    ghl_tags: List[str]
    notion_status: Optional[str]
    notion_opportunity_stage: Optional[str]
    last_outbound_touch: Optional[str]
    last_inbound_touch: Optional[str]
    last_automation_touch: Optional[str]
    last_appointment: Optional[str]
    activity_summary: str
    risk_flags: List[str]
    recommended_bucket: str
    recommended_ghl_tags: List[str]
    recommended_close_update: Optional[str]
    confidence: float
    reason: str


def _csv_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "|".join(str(x) for x in v)
    return str(v)


def _summary_counts(rows: List[ReportRow]) -> Dict[str, Any]:
    by_bucket: Counter = Counter()
    by_flag: Counter = Counter()
    for r in rows:
        by_bucket[r.recommended_bucket] += 1
        for flag in r.risk_flags:
            by_flag[flag] += 1
    return {
        "total": len(rows),
        "by_bucket": dict(by_bucket),
        "by_risk_flag": dict(by_flag),
    }


def write_report(rows: List[ReportRow], out_dir: Path) -> Dict[str, Any]:
    """Write CSV + JSON to out_dir. Returns paths and summary counts."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "lead_hygiene_report.csv"
    json_path = out_dir / "lead_hygiene_report.json"

    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for r in rows:
            d = asdict(r)
            writer.writerow({col: _csv_value(d.get(col)) for col in REPORT_COLUMNS})

    summary = _summary_counts(rows)
    json_path.write_text(json.dumps(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "rows": [asdict(r) for r in rows],
        },
        indent=2,
        default=str,
    ))

    return {
        "csv_path": csv_path,
        "json_path": json_path,
        "summary": summary,
    }


def build_report_row(
    *,
    close_record: Dict[str, Any],
    match: MatchResult,
    classification: ClassificationResult,
    notion_record: Optional[Dict[str, Any]] = None,
    ghl_record: Optional[Dict[str, Any]] = None,
) -> ReportRow:
    phones = [normalize_phone(p) for p in close_record.get("phones", []) if normalize_phone(p)]
    emails = [normalize_email(e) for e in close_record.get("emails", []) if normalize_email(e)]
    return ReportRow(
        lead_name=normalize_name(close_record.get("name", "")),
        phone=phones[0] if phones else "",
        email=emails[0] if emails else "",
        close_lead_id=close_record.get("source_id", ""),
        ghl_contact_id=match.ghl_id,
        notion_page_id=match.notion_id,
        close_status=close_record.get("close_status"),
        cadence_stage=close_record.get("cadence_stage"),
        ghl_tags=(ghl_record or {}).get("tags", []) or [],
        notion_status=(notion_record or {}).get("notion_status"),
        notion_opportunity_stage=(notion_record or {}).get("notion_opportunity_stage"),
        last_outbound_touch=classification.last_outbound_touch,
        last_inbound_touch=classification.last_inbound_touch,
        last_automation_touch=classification.last_automation_touch,
        last_appointment=classification.last_appointment,
        activity_summary=classification.activity_summary,
        risk_flags=classification.risk_flags,
        recommended_bucket=classification.recommended_bucket,
        recommended_ghl_tags=classification.recommended_ghl_tags,
        recommended_close_update=classification.recommended_close_update,
        confidence=classification.confidence,
        reason=classification.reason,
    )
