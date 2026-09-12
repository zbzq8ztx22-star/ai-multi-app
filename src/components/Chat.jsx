import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, User, Bot, MessageSquare } from 'lucide-react'
import { apiPost } from '../api'

const SESSION_ID_KEY = 'ai_multi_app_chat_session_id'

function getOrCreateSessionId() {
  let id = sessionStorage.getItem(SESSION_ID_KEY)
  if (!id) {
    id = crypto.randomUUID
      ? crypto.randomUUID()
      : Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
    sessionStorage.setItem(SESSION_ID_KEY, id)
  }
  return id
}

function saveSessionId(id) {
  if (id) sessionStorage.setItem(SESSION_ID_KEY, id)
}

export default function Chat() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: "Hello! I'm your AI assistant. How can I help you today?" }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId())
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const trimmed = input.trim()
    if (!trimmed || loading) return

    const userMessage = { role: 'user', content: trimmed }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      const data = await apiPost('/api/chat', {
        message: trimmed,
        session_id: sessionId,
      })

      if (data.session_id) {
        setSessionId(data.session_id)
        saveSessionId(data.session_id)
      }

      const reply = typeof data.response === 'string' ? data.response : ''
      if (!reply) {
        throw new Error('No response received from the assistant.')
      }

      setMessages(prev => [...prev, { role: 'assistant', content: reply }])
    } catch (error) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: error?.message || 'Sorry, there was an error processing your request.' }
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-50">
      <div className="p-6 border-b border-gray-200 bg-gray-50">
        <h2 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <MessageSquare className="text-primary-600" /> AI Chat
        </h2>
        <p className="text-gray-500 mt-1">Ask anything - I'm here to help!</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-4" role="log" aria-live="polite" aria-label="Chat messages">
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'assistant' && (
              <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center flex-shrink-0 text-white shadow-sm" aria-hidden="true">
                <Bot size={18} />
              </div>
            )}
            <div
              className={`max-w-2xl rounded-2xl px-4 py-3 shadow-sm ${
                msg.role === 'user'
                  ? 'bg-primary-600 text-white rounded-br-md'
                  : 'bg-gray-50 text-gray-700 border border-gray-200 rounded-bl-md'
              }`}
            >
              <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
            </div>
            {msg.role === 'user' && (
              <div className="w-9 h-9 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 text-gray-500" aria-hidden="true">
                <User size={18} />
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex gap-3">
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center flex-shrink-0 text-white shadow-sm" aria-hidden="true">
              <Bot size={18} />
            </div>
            <div className="bg-gray-50 rounded-2xl rounded-bl-md border border-gray-200 px-4 py-3 shadow-sm">
              <Loader2 className="animate-spin text-gray-400" size={20} aria-label="Assistant is typing" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="p-6 border-t border-gray-200 bg-gray-50">
        <div className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your message..."
            className="flex-1 input-field"
            disabled={loading}
            aria-label="Message"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="btn-primary flex items-center gap-2"
            aria-label="Send message"
            title="Send message"
          >
            {loading ? <Loader2 className="animate-spin" size={20} aria-hidden="true" /> : <Send size={20} aria-hidden="true" />}
            Send
          </button>
        </div>
      </form>
    </div>
  )
}
