import { useEffect, useState } from 'react'
import { Settings as SettingsIcon, Users, Shield, Trash2, RefreshCw } from 'lucide-react'
import { apiGet, apiPost, apiPut, apiDelete } from '../api'

export default function Settings() {
  const [users, setUsers] = useState([])
  const [auditLog, setAuditLog] = useState([])
  const [error, setError] = useState('')
  const [newUser, setNewUser] = useState({ username: '', password: '', role: 'viewer' })

  const load = async () => {
    try {
      const [u, log] = await Promise.all([apiGet('/api/auth/users'), apiGet('/api/audit/log?limit=20')])
      setUsers(u); setAuditLog(log); setError('')
    } catch (err) { setError(err.message) }
  }
  useEffect(() => { load() }, [])

  const addUser = async event => {
    event.preventDefault()
    try { await apiPost('/api/auth/register', newUser); setNewUser({ username: '', password: '', role: 'viewer' }); await load() } catch (err) { setError(err.message) }
  }

  const changeRole = async (id, role) => {
    try { await apiPut(`/api/auth/users/${id}/role`, { role }); await load() } catch (err) { setError(err.message) }
  }

  const removeUser = async id => {
    try { await apiDelete(`/api/auth/users/${id}`); await load() } catch (err) { setError(err.message) }
  }

  return <div className="h-full overflow-y-auto p-8 space-y-6 bg-gray-50">
    <div className="flex items-center justify-between">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2 text-gray-900"><SettingsIcon className="text-primary-600" /> Settings</h1>
        <p className="text-gray-500 mt-1">User management and audit log</p>
      </div>
      <button onClick={load} className="btn-secondary flex items-center gap-2"><RefreshCw size={16} /> Refresh</button>
    </div>
    {error && <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">{error}</div>}

    <div className="card space-y-4">
      <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2"><Users size={20} className="text-primary-600" /> Users</h2>
      <form onSubmit={addUser} className="grid grid-cols-4 gap-3">
        <input className="input-field" required placeholder="Username" value={newUser.username} onChange={e => setNewUser({ ...newUser, username: e.target.value })} />
        <input className="input-field" type="password" required placeholder="Password" value={newUser.password} onChange={e => setNewUser({ ...newUser, password: e.target.value })} />
        <select className="input-field" value={newUser.role} onChange={e => setNewUser({ ...newUser, role: e.target.value })}><option value="viewer">Viewer</option><option value="admin">Admin</option></select>
        <button className="btn-primary">Add user</button>
      </form>
      <div className="space-y-2">{users.map(u => <div key={u.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-100"><div className="flex items-center gap-3"><span className="font-medium text-gray-900">{u.username}</span><span className={`badge ${u.role === 'admin' ? 'badge-info' : 'badge-neutral'}`}>{u.role}</span></div><div className="flex items-center gap-2"><select className="input-field text-sm w-28" value={u.role} onChange={e => changeRole(u.id, e.target.value)}><option value="viewer">Viewer</option><option value="admin">Admin</option></select><button onClick={() => removeUser(u.id)} className="text-gray-400 hover:text-red-600"><Trash2 size={16} /></button></div></div>)}</div>
    </div>

    <div className="card space-y-3">
      <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2"><Shield size={20} className="text-primary-600" /> Recent audit log</h2>
      {auditLog.length === 0 ? <p className="text-gray-400 text-sm">No audit entries yet.</p> : <div className="space-y-1 max-h-96 overflow-y-auto">{auditLog.map(entry => <div key={entry.id} className="flex justify-between text-sm py-1.5 border-b border-gray-50 last:border-0"><div><span className="text-gray-400">{entry.created_at.slice(0, 19)}</span> <span className="font-medium text-gray-900">{entry.username}</span> <span className="text-primary-600">{entry.action}</span> <span className="text-gray-500">{entry.entity_type} in {entry.module}</span></div><div className="text-gray-400 truncate ml-4">{entry.description}</div></div>)}</div>}
    </div>
  </div>
}
