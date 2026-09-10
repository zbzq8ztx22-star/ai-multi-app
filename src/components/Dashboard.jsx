import { useEffect, useState } from 'react'
import { LayoutDashboard, Users, Building2, Calculator, BookOpen, Wallet, FileText, Receipt, RefreshCw } from 'lucide-react'
import { apiGet } from '../api'

const money = value => Number(value || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

function StatCard({ icon: Icon, label, value, accent }) {
  return <div className="card flex items-center gap-4"><div className={`p-3 rounded-lg ${accent}`}><Icon size={24} /></div><div><p className="text-sm text-gray-400">{label}</p><p className="text-2xl font-bold">{value}</p></div></div>
}

export default function Dashboard({ onNavigate }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try { setData(await apiGet('/api/dashboard/overview')); setError('') } catch (err) { setError(err.message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  if (error) return <div className="h-full overflow-y-auto p-6"><div className="p-4 bg-red-900/20 border border-red-800 rounded-lg text-red-200">{error}</div><button className="btn-secondary mt-4" onClick={load}>Retry</button></div>
  if (!data) return <div className="h-full flex items-center justify-center text-gray-400">Loading dashboard...</div>

  const c = data.counts
  const quickLinks = [
    { id: 'payroll', name: 'Payroll', icon: Wallet, desc: `${c.employees} employees` },
    { id: 'tax', name: 'Personal Tax', icon: Calculator, desc: `${c.tax_returns} returns` },
    { id: 'accounting', name: 'Accounting', icon: BookOpen, desc: `${c.businesses} businesses` },
    { id: 'chat', name: 'AI Chat', icon: FileText, desc: 'OpenExecutive' },
  ]

  return <div className="h-full overflow-y-auto p-6 space-y-6">
    <div className="flex items-center justify-between"><div><h1 className="text-2xl font-bold flex items-center gap-2"><LayoutDashboard className="text-primary-400" /> Dashboard</h1><p className="text-gray-400 mt-1">Overview across all modules</p></div><button onClick={load} className="btn-secondary flex items-center gap-2" disabled={loading}><RefreshCw size={16} /> Refresh</button></div>

    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      <StatCard icon={Users} label="Employees" value={c.employees} accent="bg-blue-900/40 text-blue-400" />
      <StatCard icon={Wallet} label="Payslips" value={c.payslips} accent="bg-green-900/40 text-green-400" />
      <StatCard icon={Calculator} label="Tax returns" value={c.tax_returns} accent="bg-purple-900/40 text-purple-400" />
      <StatCard icon={Building2} label="Businesses" value={c.businesses} accent="bg-orange-900/40 text-orange-400" />
      <StatCard icon={BookOpen} label="Posted entries" value={c.posted_entries} accent="bg-teal-900/40 text-teal-400" />
      <StatCard icon={Receipt} label="Open invoices" value={c.open_invoices} accent="bg-red-900/40 text-red-400" />
    </div>

    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {quickLinks.map(link => { const Icon = link.icon; return <button key={link.id} onClick={() => onNavigate?.(link.id)} className="card text-left hover:border-primary-500 transition-colors group"><div className="flex items-center gap-3"><div className="p-2 rounded-lg bg-gray-700 group-hover:bg-primary-600 group-hover:text-white transition-colors"><Icon size={20} /></div><div><p className="font-semibold">{link.name}</p><p className="text-sm text-gray-400">{link.desc}</p></div></div></button> })}
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="card"><h2 className="text-lg font-semibold mb-3">Recent payslips</h2>{data.recent.payslips.length === 0 ? <p className="text-gray-400 text-sm">No payslips yet.</p> : <div className="space-y-2">{data.recent.payslips.map(p => <div key={p.id} className="flex justify-between text-sm py-1"><span>{p.employee_name}</span><span className="text-gray-400">{money(p.net_pay)}</span></div>)}</div>}</div>
      <div className="card"><h2 className="text-lg font-semibold mb-3">Recent journal entries</h2>{data.recent.entries.length === 0 ? <p className="text-gray-400 text-sm">No entries yet.</p> : <div className="space-y-2">{data.recent.entries.map(e => <div key={e.id} className="flex justify-between text-sm py-1"><span className="truncate">{e.description}</span><span className={`text-xs ${e.status === 'posted' ? 'text-green-400' : 'text-yellow-400'}`}>{e.status}</span></div>)}</div>}</div>
      <div className="card"><h2 className="text-lg font-semibold mb-3">Recent tax returns</h2>{data.recent.returns.length === 0 ? <p className="text-gray-400 text-sm">No returns yet.</p> : <div className="space-y-2">{data.recent.returns.map(r => <div key={r.id} className="flex justify-between text-sm py-1"><span>{r.taxpayer_name} · {r.tax_year}</span><span className={`text-xs ${r.status === 'filed' ? 'text-green-400' : r.status === 'reviewed' ? 'text-blue-400' : 'text-gray-400'}`}>{r.status}</span></div>)}</div>}</div>
    </div>
  </div>
}
