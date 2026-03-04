import { useState } from 'react'
import { ClerkProvider, SignIn, SignedIn, SignedOut, UserButton } from '@clerk/clerk-react'
import Dashboard from './components/Dashboard'
import LeadImport from './components/LeadImport'
import Licenses from './components/Licenses'
import SyncManagement from './components/SyncManagement'
import Analytics from './components/Analytics'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'leads', label: 'Lead Import' },
  { key: 'licenses', label: 'Licenses' },
  { key: 'sync', label: 'Sync' },
  { key: 'analytics', label: 'Analytics' },
]

function PageContent({ currentPage }) {
  switch (currentPage) {
    case 'leads':
      return <LeadImport />
    case 'licenses':
      return <Licenses />
    case 'sync':
      return <SyncManagement />
    case 'analytics':
      return <Analytics />
    default:
      return <Dashboard />
  }
}

function AppLayout() {
  const [currentPage, setCurrentPage] = useState('dashboard')

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-wordmark">
            FALCON<br />CONNECT
          </div>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              className={`nav-item ${currentPage === item.key ? 'active' : ''}`}
              onClick={() => setCurrentPage(item.key)}
            >
              <span className="nav-indicator" />
              {item.label}
            </button>
          ))}
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
        <PageContent currentPage={currentPage} />
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
