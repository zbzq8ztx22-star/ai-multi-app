import { useState } from 'react'
import { MessageSquare, Image, Code, FileText, Menu, X } from 'lucide-react'
import Chat from './components/Chat'
import Vision from './components/Vision'
import CodeGen from './components/CodeGen'
import Docs from './components/Docs'

function App() {
  const [activeTab, setActiveTab] = useState('chat')
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const tabs = [
    { id: 'chat', name: 'Chat', icon: MessageSquare },
    { id: 'vision', name: 'Vision', icon: Image },
    { id: 'code', name: 'Code', icon: Code },
    { id: 'docs', name: 'Documents', icon: FileText },
  ]

  return (
    <div className="flex h-screen bg-gray-900">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-64' : 'w-16'} bg-gray-800 border-r border-gray-700 transition-all duration-300`}>
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          {sidebarOpen && <h1 className="text-xl font-bold text-primary-400">AI Multi-App</h1>}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
          >
            {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
        
        <nav className="p-4 space-y-2">
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
              >
                <Icon size={20} />
                {sidebarOpen && <span>{tab.name}</span>}
              </button>
            )
          })}
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-hidden">
        {activeTab === 'chat' && <Chat />}
        {activeTab === 'vision' && <Vision />}
        {activeTab === 'code' && <CodeGen />}
        {activeTab === 'docs' && <Docs />}
      </main>
    </div>
  )
}

export default App
