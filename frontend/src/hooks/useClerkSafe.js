/**
 * Safe wrappers for Clerk hooks that work both inside and outside ClerkProvider.
 *
 * When VITE_CLERK_PUBLISHABLE_KEY is not set (dev mode / bypass), ClerkProvider
 * is not rendered, and bare useAuth() / useUser() hooks throw. These wrappers
 * return sensible no-op defaults so components render without crashing.
 */
import { useAuth as _useAuth, useUser as _useUser } from '@clerk/clerk-react'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY
const DEV_BYPASS = import.meta.env.VITE_DEV_BYPASS === 'true'
const HAS_CLERK = !DEV_BYPASS && !!PUBLISHABLE_KEY

/**
 * Safe useAuth — returns { getToken, isLoaded, isSignedIn, ... }
 * Outside ClerkProvider: getToken() returns null, isSignedIn is false.
 */
export function useAuthSafe() {
  if (!HAS_CLERK) {
    return {
      getToken: async () => null,
      isLoaded: true,
      isSignedIn: false,
      userId: null,
      sessionId: null,
      orgId: null,
    }
  }
  return _useAuth()
}

/**
 * Safe useUser — returns { user, isLoaded, isSignedIn }
 * Outside ClerkProvider: user is null.
 */
export function useUserSafe() {
  if (!HAS_CLERK) {
    return {
      user: null,
      isLoaded: true,
      isSignedIn: false,
    }
  }
  return _useUser()
}
