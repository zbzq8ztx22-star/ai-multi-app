import { useState } from 'react'
import { Loader2, LogIn, LayoutDashboard } from 'lucide-react'
import { apiPost } from '../api'

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const user = await apiPost('/api/auth/login', { username, password })
      onLogin(user)
    } catch (err) {
      setError(err?.message || 'Login failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 via-primary-50/30 to-gray-100 p-4">
      <form onSubmit={handleSubmit} className="card w-full max-w-sm space-y-6 bg-gray-50">
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 mb-4 shadow-lg shadow-primary-500/20">
            <LayoutDashboard size={28} className="text-white" aria-hidden="true" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">AI Multi-App</h1>
          <p className="text-gray-500 mt-1">Sign in to continue</p>
        </div>

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-1.5">Username</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full input-field"
              required
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1.5">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full input-field"
              required
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={loading || !username.trim() || !password.trim()}
          className="btn-primary w-full flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 className="animate-spin" size={18} aria-hidden="true" /> : <LogIn size={18} aria-hidden="true" />}
          Sign In
        </button>
      </form>
    </div>
  )
}
