import { useEffect, useState } from 'react'
import { Building2, Calculator, Plus, RefreshCw, UserRound } from 'lucide-react'
import { apiGet, apiPost } from '../api'

const EMPTY_TAXPAYER = {
  legal_name: '', employee_id: '', taxpayer_type: 'individual', filing_status: 'single',
  residence_state: '', identifier_last4: '', email: '', phone: '', address: '',
}

export default function Tax() {
  const [taxpayers, setTaxpayers] = useState([])
  const [businesses, setBusinesses] = useState([])
  const [employees, setEmployees] = useState([])
  const [form, setForm] = useState(EMPTY_TAXPAYER)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const [people, companies, staff] = await Promise.all([
        apiGet('/api/entities/taxpayers'), apiGet('/api/entities/businesses'), apiGet('/api/payroll/employees'),
      ])
      setTaxpayers(people)
      setBusinesses(companies)
      setEmployees(staff)
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const submit = async (event) => {
    event.preventDefault()
    setLoading(true)
    try {
      await apiPost('/api/entities/taxpayers', { ...form, employee_id: form.employee_id || null })
      setForm(EMPTY_TAXPAYER)
      await refresh()
    } catch (err) {
      setError(err.message)
      setLoading(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><Calculator className="text-primary-400" /> Tax</h1>
          <p className="text-gray-400 mt-1">Personal and corporate tax workspace</p>
        </div>
        <button onClick={refresh} className="btn-secondary flex items-center gap-2"><RefreshCw size={16} /> Refresh</button>
      </div>
      {error && <div className="p-4 bg-red-900/20 border border-red-800 rounded-lg text-red-200">{error}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <form onSubmit={submit} className="card space-y-4">
          <h2 className="text-lg font-semibold flex items-center gap-2"><UserRound size={20} /> New taxpayer</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input className="input-field" placeholder="Legal name" required value={form.legal_name} onChange={e => setForm({ ...form, legal_name: e.target.value })} />
            <select className="input-field" value={form.employee_id} onChange={e => setForm({ ...form, employee_id: e.target.value })}>
              <option value="">No payroll link</option>
              {employees.map(employee => <option key={employee.id} value={employee.id}>{employee.name}</option>)}
            </select>
            <select className="input-field" value={form.filing_status} onChange={e => setForm({ ...form, filing_status: e.target.value })}>
              <option value="single">Single</option><option value="married_joint">Married filing jointly</option>
              <option value="married_separate">Married filing separately</option><option value="hoh">Head of household</option>
              <option value="widow">Qualifying surviving spouse</option>
            </select>
            <input className="input-field" placeholder="Residence state" value={form.residence_state} onChange={e => setForm({ ...form, residence_state: e.target.value })} />
            <input className="input-field" placeholder="SSN last 4 only" maxLength="4" value={form.identifier_last4} onChange={e => setForm({ ...form, identifier_last4: e.target.value })} />
            <input className="input-field" type="email" placeholder="Email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />
            <input className="input-field" placeholder="Phone" value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} />
            <input className="input-field" placeholder="Address" value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} />
          </div>
          <button className="btn-primary flex items-center gap-2" disabled={loading}><Plus size={16} /> Add taxpayer</button>
        </form>

        <div className="card">
          <h2 className="text-lg font-semibold mb-4">Taxpayers</h2>
          {taxpayers.length === 0 ? <p className="text-gray-400">No taxpayers yet.</p> : (
            <div className="space-y-3">{taxpayers.map(person => (
              <div key={person.id} className="p-3 rounded-lg bg-gray-800 flex justify-between">
                <div><p className="font-medium">{person.legal_name}</p><p className="text-sm text-gray-400">{person.filing_status.replaceAll('_', ' ')} · {person.residence_state || 'No state'}</p></div>
                <span className="text-xs text-gray-400">{person.employee_id ? 'Payroll linked' : 'Independent'}</span>
              </div>
            ))}</div>
          )}
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold flex items-center gap-2 mb-3"><Building2 size={20} /> Corporate tax</h2>
        <p className="text-gray-400 mb-4">Corporate returns will use businesses and financial results from Accounting.</p>
        {businesses.length === 0 ? <p className="text-sm text-gray-500">Create a business in Accounting to begin.</p> : businesses.map(business => <div key={business.id} className="py-2 border-b border-gray-700 last:border-0">{business.legal_name} · {business.entity_type.replaceAll('_', ' ')}</div>)}
      </div>
    </div>
  )
}
