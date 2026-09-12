import { useEffect, useState } from 'react'
import { LayoutDashboard, Users, Building2, Calculator, BookOpen, Wallet, FileText, Receipt, RefreshCw, Loader2 } from 'lucide-react'
import { apiGet } from '../api'

const money = value => Number(value || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

function StatCard({ icon: Icon, label, value, accent }) {
  return (
    <div className="card flex items-center gap-4">
      <div className={`p-3 rounded-xl ${accent}`}>
        <Icon size={24} />
      </div>
      <div>
        <p className="text-sm text-gray-500">{label}</p>
        <p className="text-2xl font-bold text-gray-900">{value}</p>
      </div>
    </div>
  )
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

  if (error) return (
    <div className="h-full overflow-y-auto p-8">
      <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">{error}</div>
      <button className="btn-secondary mt-4" onClick={load}>Retry</button>
    </div>
  )
  if (!data) return (
    <div className="h-full flex items-center justify-center text-gray-400">
      <Loader2 className="animate-spin mr-2" size={20} /> Loading dashboard...
    </div>
  )

  const c = data.counts
  const quickLinks = [
    { id: 'payroll', name: 'Payroll', icon: Wallet, desc: `${c.employees} employees` },
    { id: 'tax', name: 'Personal Tax', icon: Calculator, desc: `${c.tax_returns} returns` },
    { id: 'accounting', name: 'Accounting', icon: BookOpen, desc: `${c.businesses} businesses` },
    { id: 'chat', name: 'AI Chat', icon: FileText, desc: 'OpenExecutive' },
  ]

  return (
    <div className="h-full overflow-y-auto p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2 text-gray-900">
            <LayoutDashboard className="text-primary-600" /> Dashboard
          </h1>
          <p className="text-gray-500 mt-1">Overview across all modules</p>
        </div>
        <button onClick={load} className="btn-secondary flex items-center gap-2" disabled={loading}>
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard icon={Users} label="Employees" value={c.employees} accent="bg-blue-50 text-blue-600" />
        <StatCard icon={Wallet} label="Payslips" value={c.payslips} accent="bg-emerald-50 text-emerald-600" />
        <StatCard icon={Calculator} label="Tax returns" value={c.tax_returns} accent="bg-purple-50 text-purple-600" />
        <StatCard icon={Building2} label="Businesses" value={c.businesses} accent="bg-orange-50 text-orange-600" />
        <StatCard icon={BookOpen} label="Posted entries" value={c.posted_entries} accent="bg-teal-50 text-teal-600" />
        <StatCard icon={Receipt} label="Open invoices" value={c.open_invoices} accent="bg-red-50 text-red-600" />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-3">Quick links</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {quickLinks.map(link => {
            const Icon = link.icon
            return (
              <button key={link.id} onClick={() => onNavigate?.(link.id)} className="card text-left group">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-xl bg-gray-50 group-hover:bg-primary-600 group-hover:text-white transition-colors text-gray-400">
                    <Icon size={20} />
                  </div>
                  <div>
                    <p className="font-semibold text-gray-900">{link.name}</p>
                    <p className="text-sm text-gray-500">{link.desc}</p>
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Recent payslips</h2>
          {data.recent.payslips.length === 0 ? <p className="text-gray-400 text-sm">No payslips yet.</p> : (
            <div className="space-y-2">
              {data.recent.payslips.map(p => (
                <div key={p.id} className="flex justify-between text-sm py-1.5 border-b border-gray-50 last:border-0">
                  <span className="text-gray-700">{p.employee_name}</span>
                  <span className="text-gray-500 font-medium">{money(p.net_pay)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Recent journal entries</h2>
          {data.recent.entries.length === 0 ? <p className="text-gray-400 text-sm">No entries yet.</p> : (
            <div className="space-y-2">
              {data.recent.entries.map(e => (
                <div key={e.id} className="flex justify-between text-sm py-1.5 border-b border-gray-50 last:border-0">
                  <span className="text-gray-700 truncate">{e.description}</span>
                  <span className={`badge ${e.status === 'posted' ? 'badge-success' : 'badge-warning'}`}>{e.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Recent tax returns</h2>
          {data.recent.returns.length === 0 ? <p className="text-gray-400 text-sm">No returns yet.</p> : (
            <div className="space-y-2">
              {data.recent.returns.map(r => (
                <div key={r.id} className="flex justify-between text-sm py-1.5 border-b border-gray-50 last:border-0">
                  <span className="text-gray-700">{r.taxpayer_name} · {r.tax_year}</span>
                  <span className={`badge ${r.status === 'filed' ? 'badge-success' : r.status === 'reviewed' ? 'badge-info' : 'badge-neutral'}`}>{r.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
