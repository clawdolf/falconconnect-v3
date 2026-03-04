import { ClerkProvider, SignIn, SignedIn, SignedOut, UserButton } from '@clerk/clerk-react'
import Dashboard from './components/Dashboard'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

function AppLayout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-wordmark">
            FALCON<br />CONNECT
          </div>
        </div>
        <nav className="sidebar-nav">
          <button className="nav-item active">
            <span className="nav-indicator" />
            Dashboard
          </button>
        </nav>
        <div className="sidebar-footer">
          <UserButton
            appearance={{
              elements: {
                avatarBox: {
                  width: 28,
                  height: 28,
                },
              },
            }}
          />
        </div>
      </aside>
      <main className="main-content">
        <Dashboard />
      </main>
    </div>
  )
}

function App() {
  // No Clerk key — show dashboard without auth
  if (!PUBLISHABLE_KEY) {
    return (
      <div className="app-noauth">
        <header className="header-noauth">
          <span className="header-noauth-title">FalconConnect</span>
          <span className="badge-noauth">Auth not configured</span>
        </header>
        <Dashboard />
      </div>
    )
  }

  return (
    <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
      <SignedOut>
        <div className="auth-screen">
          <div className="auth-card">
            <h1 className="auth-wordmark">FALCONCONNECT</h1>
            <hr className="auth-rule" />
            <p className="auth-subtitle">Internal System</p>
            <SignIn />
          </div>
        </div>
      </SignedOut>
      <SignedIn>
        <AppLayout />
      </SignedIn>
    </ClerkProvider>
  )
}

export default App
