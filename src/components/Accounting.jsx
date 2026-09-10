import { useEffect, useState } from 'react'
import { BarChart3, BookOpen, Building2, Plus, Receipt } from 'lucide-react'
import { apiGet, apiPost } from '../api'

const EMPTY_BUSINESS = {
  legal_name: '', dba_name: '', entity_type: 'llc', ein_last4: '',
  formation_state: '', fiscal_year_end: '12-31', accounting_method: 'cash',
}

export default function Accounting() {
  const [businesses, setBusinesses] = useState([])
  const [form, setForm] = useState(EMPTY_BUSINESS)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    try {
      setBusinesses(await apiGet('/api/entities/businesses'))
      setError('')
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => { refresh() }, [])

  const submit = async (event) => {
    event.preventDefault()
    setLoading(true)
    try {
      await apiPost('/api/entities/businesses', form)
      setForm(EMPTY_BUSINESS)
      await refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><BookOpen className="text-primary-400" /> Accounting</h1>
        <p className="text-gray-400 mt-1">Business accounting foundation</p>
      </div>
      {error && <div className="p-4 bg-red-900/20 border border-red-800 rounded-lg text-red-200">{error}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <form onSubmit={submit} className="card space-y-4">
          <h2 className="text-lg font-semibold flex items-center gap-2"><Building2 size={20} /> Add business</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input className="input-field" required placeholder="Legal name" value={form.legal_name} onChange={e => setForm({ ...form, legal_name: e.target.value })} />
            <input className="input-field" placeholder="DBA name" value={form.dba_name} onChange={e => setForm({ ...form, dba_name: e.target.value })} />
            <select className="input-field" value={form.entity_type} onChange={e => setForm({ ...form, entity_type: e.target.value })}>
              <option value="sole_proprietorship">Sole proprietorship</option><option value="llc">LLC</option>
              <option value="partnership">Partnership</option><option value="s_corp">S Corporation</option>
              <option value="c_corp">C Corporation</option><option value="nonprofit">Nonprofit</option>
            </select>
            <input className="input-field" placeholder="EIN last 4 only" maxLength="4" value={form.ein_last4} onChange={e => setForm({ ...form, ein_last4: e.target.value })} />
            <input className="input-field" placeholder="Formation state" value={form.formation_state} onChange={e => setForm({ ...form, formation_state: e.target.value })} />
            <input className="input-field" placeholder="Fiscal year end MM-DD" value={form.fiscal_year_end} onChange={e => setForm({ ...form, fiscal_year_end: e.target.value })} />
            <select className="input-field" value={form.accounting_method} onChange={e => setForm({ ...form, accounting_method: e.target.value })}>
              <option value="cash">Cash method</option><option value="accrual">Accrual method</option>
            </select>
          </div>
          <button className="btn-primary flex items-center gap-2" disabled={loading}><Plus size={16} /> Add business</button>
        </form>

        <div className="card">
          <h2 className="text-lg font-semibold mb-4">Businesses</h2>
          {businesses.length === 0 ? <p className="text-gray-400">No businesses yet.</p> : (
            <div className="space-y-3">{businesses.map(business => (
              <div key={business.id} className="p-3 rounded-lg bg-gray-800">
                <p className="font-medium">{business.legal_name}</p>
                <p className="text-sm text-gray-400">{business.entity_type.replaceAll('_', ' ')} · {business.accounting_method} basis · FY {business.fiscal_year_end}</p>
              </div>
            ))}</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          [BookOpen, 'General Ledger', 'Chart of accounts and balanced journal entries'],
          [Receipt, 'Operations', 'Invoices, expenses, customers and vendors'],
          [BarChart3, 'Financial Reports', 'Profit & Loss, Balance Sheet and Cash Flow'],
        ].map(([Icon, title, text]) => <div key={title} className="card"><Icon className="text-primary-400 mb-3" /><h3 className="font-semibold">{title}</h3><p className="text-sm text-gray-400 mt-1">{text}</p><span className="text-xs text-primary-400 mt-3 inline-block">Next phase</span></div>)}
      </div>
    </div>
  )
}
