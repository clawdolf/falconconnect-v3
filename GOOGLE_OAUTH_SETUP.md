# Google OAuth Setup — FalconConnect Private Sheets Access

This enables users who sign in with Google to access **private** Google Sheets
directly from the Accountability Tracker panel, using their own Google account
permissions (no service account required).

---

## Step 1 — Clerk Dashboard Configuration

1. Go to [https://dashboard.clerk.com](https://dashboard.clerk.com) and open your FalconConnect application.
2. Navigate to **User & Authentication → Social Connections**.
3. Find **Google** in the list and enable it (toggle on).
4. Click the **Google** row to expand its settings.
5. Under **Scopes**, add the following scope (in addition to the defaults):
   ```
   https://www.googleapis.com/auth/spreadsheets.readonly
   ```
6. Click **Save**.

> **Why this scope?** It allows the app to read (but not write) any spreadsheet
> the signed-in Google user has access to. The token is issued by Google and
> passed through Clerk — FalconConnect never stores it.

---

## Step 2 — Google Cloud Console (if using custom OAuth credentials)

If Clerk is configured with your own Google OAuth app (not Clerk's shared
credentials):

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com).
2. Select your project → **APIs & Services → Credentials**.
3. Edit the OAuth 2.0 Client ID used by Clerk.
4. Under **Authorized redirect URIs**, confirm the Clerk callback URL is listed
   (Clerk provides this — check `https://accounts.<your-clerk-domain>/v1/oauth_callback`).
5. Enable the **Google Sheets API** under **APIs & Services → Library** if not
   already enabled.

---

## How It Works (Technical)

- When a user signs in with Google, Clerk stores a Google access token in their
  session.
- The frontend calls `getToken({ template: 'google' })` to retrieve this token.
- The token is sent to the backend via the `X-Google-Token` header.
- The backend calls the Google Sheets API on behalf of the user using their
  token — no server-side API key needed.
- Users who signed in with email/password will fall back to public sheet access
  only.

---

## Testing

1. Sign out and sign back in with **Continue with Google**.
2. Open the **Analytics** page → **Accountability Tracker** → **Settings**.
3. Paste a private sheet URL (one your Google account can access).
4. Click **Fetch Latest Data** — it should load without error.

If you see "Sheet is not accessible with your Google account", the sheet is
either truly private to a different account, or the scope was not granted during
the OAuth flow (re-sign-in with Google to force token refresh).
