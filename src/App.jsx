import { useEffect, useState } from 'react'
import { MessageSquare, Image, Code, FileText, Wallet, Menu, X, LogOut, Loader2 } from 'lucide-react'
import { apiGet, apiPost } from './api'
import Chat from './components/Chat'
import Vision from './components/Vision'
import CodeGen from './components/CodeGen'
import Docs from './components/Docs'
import Login from './components/Login'
import Payroll from './components/Payroll'

function App() {
  const [activeTab, setActiveTab] = useState('chat')
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
    { id: 'chat', name: 'Chat', icon: MessageSquare },
    { id: 'vision', name: 'Vision', icon: Image },
    { id: 'code', name: 'Code', icon: Code },
    { id: 'docs', name: 'Documents', icon: FileText },
    { id: 'payroll', name: 'Payroll', icon: Wallet },
  ]

  if (authLoading) {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-900">
        <Loader2 className="animate-spin text-primary-400" size={32} aria-label="Loading" />
      </div>
    )
  }

  if (!user) {
    return <Login onLogin={setUser} />
  }

  return (
    <div className="flex h-screen bg-gray-900">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-64' : 'w-16'} bg-gray-800 border-r border-gray-700 transition-all duration-300`}>
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          {sidebarOpen && <h1 className="text-xl font-bold text-primary-400">AI Multi-App</h1>}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          >
            {sidebarOpen ? <X size={20} aria-hidden="true" /> : <Menu size={20} aria-hidden="true" />}
          </button>
        </div>
        
        <nav className="p-4 space-y-2" role="tablist" aria-label="Application sections">
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  activeTab === tab.id
                    ? 'bg-primary-600 text-white'
                    : 'hover:bg-gray-700 text-gray-300'
                }`}
                id={`${tab.id}-tab`}
                role="tab"
                aria-label={tab.name}
                aria-selected={activeTab === tab.id}
                aria-controls={`${tab.id}-panel`}
                title={tab.name}
              >
                <Icon size={20} aria-hidden="true" />
                {sidebarOpen && <span>{tab.name}</span>}
              </button>
            )
          })}
        </nav>

        <div className="mt-auto p-4 border-t border-gray-700">
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-gray-700 text-gray-300 transition-colors"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut size={20} aria-hidden="true" />
            {sidebarOpen && <span>Sign out</span>}
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
        {activeTab === 'chat' && <Chat />}
        {activeTab === 'vision' && <Vision />}
        {activeTab === 'code' && <CodeGen />}
        {activeTab === 'docs' && <Docs />}
        {activeTab === 'payroll' && <Payroll />}
      </main>
    </div>
  )
}

export default App
