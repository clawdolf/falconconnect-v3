"""Google Sheets private access via user's Google OAuth token (passed from Clerk)."""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from middleware.auth import require_auth

logger = logging.getLogger("falconconnect.sheets")

router = APIRouter()

SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


@router.get("/data")
async def get_sheet_data(
    sheet_id: str = Query(..., description="Google Sheets spreadsheet ID"),
    x_google_token: Optional[str] = Header(None, alias="X-Google-Token"),
    user=Depends(require_auth),
):
    """Fetch data from a Google Sheet using the user's Google OAuth token.

    Requires:
    - Valid Clerk session (Authorization: Bearer <clerk_token>)
    - Google OAuth token in X-Google-Token header (obtained from Clerk when
      the user signed in with Google and granted sheets.readonly scope)

    Returns rows and sheet title. The Google token is used directly against
    the Sheets API — no service account or backend API key needed.
    """
    if not x_google_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Google-Token header is required. Sign in with Google to access private sheets.",
        )

    url = f"{SHEETS_API_BASE}/{sheet_id}/values/A1:Z1000"
    params = {"majorDimension": "ROWS"}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {x_google_token}"},
            )
        except httpx.RequestError as e:
            logger.error("Google Sheets request error: %s", e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to reach Google Sheets API.",
            )

    if resp.status_code == 403:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Sheet is not accessible with your Google account. "
                "Check permissions or make it public."
            ),
        )

    if resp.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Spreadsheet not found. Verify the sheet ID.",
        )

    if resp.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google token expired or invalid. Please sign out and sign in with Google again.",
        )

    if not resp.is_success:
        logger.warning(
            "Google Sheets API returned %s for sheet %s: %s",
            resp.status_code, sheet_id, resp.text[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Sheets API error: HTTP {resp.status_code}",
        )

    payload = resp.json()
    raw_rows: list[list] = payload.get("values", [])

    if not raw_rows:
        return {"rows": [], "headers": [], "sheet_title": sheet_id}

    # First row = headers, remainder = data rows
    headers = [str(c) for c in raw_rows[0]]
    data_rows = raw_rows[1:]

    # Pad short rows so every row has the same length as headers
    padded = [row + [""] * (len(headers) - len(row)) for row in data_rows]

    # BUG 10 FIX: Metadata fetch was using already-closed httpx client.
    # Now uses a separate client context for the metadata call.
    sheet_title = sheet_id
    try:
        async with httpx.AsyncClient(timeout=10) as meta_client:
            meta_resp = await meta_client.get(
                f"{SHEETS_API_BASE}/{sheet_id}",
                params={"fields": "properties.title"},
                headers={"Authorization": f"Bearer {x_google_token}"},
            )
            if meta_resp.is_success:
                sheet_title = (
                    meta_resp.json()
                    .get("properties", {})
                    .get("title", sheet_id)
                )
    except Exception:
        pass  # non-fatal

    return {
        "rows": padded,
        "headers": headers,
        "sheet_title": sheet_title,
    }
