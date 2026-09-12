import { useEffect, useState } from 'react'
import { MessageSquare, Image, Calculator, FileText, Wallet, Menu, X, LogOut, Loader2, BookOpen, LayoutDashboard, Settings as SettingsIcon } from 'lucide-react'
import { apiGet, apiPost } from './api'
import Accounting from './components/Accounting'
import Chat from './components/Chat'
import Dashboard from './components/Dashboard'
import Docs from './components/Docs'
import Login from './components/Login'
import Payroll from './components/Payroll'
import Settings from './components/Settings'
import Tax from './components/Tax'
import Vision from './components/Vision'

function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [user, setUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)

  useEffect(() => {
    apiGet('/api/auth/me')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false))
  }, [])

  const handleLogout = async () => {
    try {
      await apiPost('/api/auth/logout', {})
    } finally {
      setUser(null)
    }
  }

  const tabs = [
    { id: 'dashboard', name: 'Dashboard', icon: LayoutDashboard },
    { id: 'chat', name: 'Chat', icon: MessageSquare },
    { id: 'vision', name: 'Vision', icon: Image },
    { id: 'tax', name: 'Tax', icon: Calculator },
    { id: 'accounting', name: 'Accounting', icon: BookOpen },
    { id: 'docs', name: 'Documents', icon: FileText },
    { id: 'payroll', name: 'Payroll', icon: Wallet },
    { id: 'settings', name: 'Settings', icon: SettingsIcon },
  ]

  if (authLoading) {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="animate-spin text-primary-500" size={32} aria-label="Loading" />
      </div>
    )
  }

  if (!user) {
    return <Login onLogin={setUser} />
  }

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-64' : 'w-16'} bg-gray-50 border-r border-gray-200 transition-all duration-300 flex flex-col`}>
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          {sidebarOpen && (
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center">
                <LayoutDashboard size={18} className="text-white" aria-hidden="true" />
              </div>
              <h1 className="text-lg font-bold text-gray-900">AI Multi-App</h1>
            </div>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors text-gray-500"
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          >
            {sidebarOpen ? <X size={20} aria-hidden="true" /> : <Menu size={20} aria-hidden="true" />}
          </button>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto" role="tablist" aria-label="Application sections">
          {tabs.map((tab) => {
            const Icon = tab.icon
            const active = activeTab === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all font-medium ${
                  active
                    ? 'bg-primary-50 text-primary-700'
                    : 'hover:bg-gray-50 text-gray-600 hover:text-gray-900'
                }`}
                id={`${tab.id}-tab`}
                role="tab"
                aria-label={tab.name}
                aria-selected={active}
                aria-controls={`${tab.id}-panel`}
                title={tab.name}
              >
                <Icon size={20} aria-hidden="true" className={active ? 'text-primary-600' : 'text-gray-400'} />
                {sidebarOpen && <span className="text-sm">{tab.name}</span>}
              </button>
            )
          })}
        </nav>

        <div className="p-3 border-t border-gray-100">
          {sidebarOpen && user && (
            <div className="flex items-center gap-3 px-3 py-2 mb-1">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center text-white text-sm font-semibold">
                {user.username?.[0]?.toUpperCase() || 'U'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">{user.username}</p>
                <p className="text-xs text-gray-400 capitalize">{user.role}</p>
              </div>
            </div>
          )}
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-gray-50 text-gray-500 hover:text-gray-900 transition-colors"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut size={20} aria-hidden="true" />
            {sidebarOpen && <span className="text-sm font-medium">Sign out</span>}
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main
        id={`${activeTab}-panel`}
        role="tabpanel"
        aria-labelledby={`${activeTab}-tab`}
        className="flex-1 overflow-hidden"
      >
        {activeTab === 'dashboard' && <Dashboard onNavigate={setActiveTab} />}
        {activeTab === 'chat' && <Chat />}
        {activeTab === 'vision' && <Vision />}
        {activeTab === 'tax' && <Tax />}
        {activeTab === 'accounting' && <Accounting />}
        {activeTab === 'docs' && <Docs />}
        {activeTab === 'payroll' && <Payroll />}
        {activeTab === 'settings' && <Settings />}
      </main>
    </div>
  )
}

export default App
