import { useEffect, useState } from 'react'
import { Building2, Calculator, Plus, RefreshCw, UserRound } from 'lucide-react'
import { apiGet, apiPost, apiPut } from '../api'

const EMPTY_TAXPAYER = { legal_name: '', employee_id: '', filing_status: 'single', residence_state: '', identifier_last4: '', email: '', phone: '', address: '' }
const MONEY_FIELDS = [
  ['wages', 'W-2 wages'], ['interest_income', 'Interest income'], ['dividend_income', 'Dividend income'],
  ['business_income', 'Business income'], ['capital_gains', 'Capital gains'], ['other_income', 'Other income'],
  ['adjustments', 'Adjustments'], ['itemized_deductions', 'Itemized deductions'], ['credits', 'Tax credits'],
  ['federal_withholding', 'Federal withholding'], ['estimated_payments', 'Estimated payments'],
  ['state_tax_liability', 'State tax liability'], ['state_withholding', 'State withholding'],
]
const EMPTY_RETURN = Object.fromEntries([['taxpayer_id', ''], ['tax_year', '2025'], ['status', 'draft'], ...MONEY_FIELDS.map(([field]) => [field, ''])])
const money = value => Number(value || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export default function Tax() {
  const [taxpayers, setTaxpayers] = useState([])
  const [businesses, setBusinesses] = useState([])
  const [employees, setEmployees] = useState([])
  const [returns, setReturns] = useState([])
  const [personForm, setPersonForm] = useState(EMPTY_TAXPAYER)
  const [returnForm, setReturnForm] = useState(EMPTY_RETURN)
  const [selectedReturnId, setSelectedReturnId] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const [people, companies, filings] = await Promise.all([
        apiGet('/api/entities/taxpayers'), apiGet('/api/entities/businesses'),
        apiGet('/api/tax/returns'),
      ])
      const staff = (await Promise.all(
        companies.map(b => apiGet(`/api/payroll/employees?business_id=${b.id}`))
      )).flat()
      setTaxpayers(people); setBusinesses(companies); setEmployees(staff); setReturns(filings); setError('')
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  useEffect(() => { refresh() }, [])

  const submitPerson = async event => {
    event.preventDefault(); setLoading(true)
    try {
      await apiPost('/api/entities/taxpayers', { ...personForm, employee_id: personForm.employee_id || null })
      setPersonForm(EMPTY_TAXPAYER); await refresh()
    } catch (err) { setError(err.message); setLoading(false) }
  }

  const submitReturn = async event => {
    event.preventDefault(); setLoading(true)
    try {
      if (selectedReturnId) await apiPut(`/api/tax/returns/${selectedReturnId}`, returnForm)
      else await apiPost('/api/tax/returns', returnForm)
      setReturnForm(EMPTY_RETURN); setSelectedReturnId(null); await refresh()
    } catch (err) { setError(err.message); setLoading(false) }
  }

  const editReturn = filing => {
    setSelectedReturnId(filing.id)
    setReturnForm(Object.fromEntries(Object.keys(EMPTY_RETURN).map(field => [field, String(filing[field] ?? '')])))
  }

  return (
    <div className="h-full overflow-y-auto p-8 space-y-6 bg-gray-50">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2 text-gray-900"><Calculator className="text-primary-600" /> Tax</h1>
          <p className="text-gray-500 mt-1">Personal and corporate tax workspace</p>
        </div>
        <button onClick={refresh} className="btn-secondary flex items-center gap-2"><RefreshCw size={16} className={loading ? 'animate-spin' : ''} /> Refresh</button>
      </div>
      {error && <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">{error}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <form onSubmit={submitPerson} className="card space-y-4">
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2"><UserRound size={20} className="text-primary-600" /> New taxpayer</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input className="input-field" placeholder="Legal name" required value={personForm.legal_name} onChange={e => setPersonForm({ ...personForm, legal_name: e.target.value })} />
            <select className="input-field" value={personForm.employee_id} onChange={e => setPersonForm({ ...personForm, employee_id: e.target.value })}><option value="">No payroll link</option>{employees.map(e => <option key={e.id} value={e.id}>{e.name}{businesses.find(b => b.id === e.business_id) ? ` · ${businesses.find(b => b.id === e.business_id).legal_name}` : ''}</option>)}</select>
            <select className="input-field" value={personForm.filing_status} onChange={e => setPersonForm({ ...personForm, filing_status: e.target.value })}><option value="single">Single</option><option value="married_joint">Married filing jointly</option><option value="married_separate">Married filing separately</option><option value="hoh">Head of household</option><option value="widow">Qualifying surviving spouse</option></select>
            <input className="input-field" placeholder="Residence state" value={personForm.residence_state} onChange={e => setPersonForm({ ...personForm, residence_state: e.target.value })} />
            <input className="input-field" placeholder="SSN last 4 only" maxLength="4" value={personForm.identifier_last4} onChange={e => setPersonForm({ ...personForm, identifier_last4: e.target.value })} />
            <input className="input-field" type="email" placeholder="Email" value={personForm.email} onChange={e => setPersonForm({ ...personForm, email: e.target.value })} />
          </div><button className="btn-primary flex items-center gap-2" disabled={loading}><Plus size={16} /> Add taxpayer</button>
        </form>
        <div className="card"><h2 className="text-lg font-semibold text-gray-900 mb-4">Taxpayers</h2>{taxpayers.length === 0 ? <p className="text-gray-400">No taxpayers yet.</p> : <div className="space-y-3">{taxpayers.map(p => <div key={p.id} className="p-3 rounded-lg bg-gray-50 border border-gray-100"><p className="font-medium text-gray-900">{p.legal_name}</p><p className="text-sm text-gray-500">{p.filing_status.replaceAll('_', ' ')} · {p.residence_state || 'No state'} · {p.employee_id ? 'Payroll linked' : 'Independent'}</p></div>)}</div>}</div>
      </div>

      <form onSubmit={submitReturn} className="card space-y-4">
        <div><h2 className="text-lg font-semibold text-gray-900">Personal return estimate</h2><p className="text-sm text-gray-500">2025 federal estimate using IRS brackets. State liability must be entered from the applicable state calculation.</p></div>
        <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-3">
          <select className="input-field" required value={returnForm.taxpayer_id} onChange={e => setReturnForm({ ...returnForm, taxpayer_id: e.target.value })}><option value="">Select taxpayer</option>{taxpayers.map(p => <option key={p.id} value={p.id}>{p.legal_name}</option>)}</select>
          <input className="input-field" value={returnForm.tax_year} disabled />
          {MONEY_FIELDS.map(([field, label]) => <input key={field} className="input-field" type="number" min="0" step="0.01" placeholder={label} value={returnForm[field]} onChange={e => setReturnForm({ ...returnForm, [field]: e.target.value })} />)}
        </div>
        <div className="flex gap-2"><button className="btn-primary" disabled={loading}>{selectedReturnId ? 'Recalculate return' : 'Calculate return'}</button>{selectedReturnId && <button type="button" className="btn-secondary" onClick={() => { setSelectedReturnId(null); setReturnForm(EMPTY_RETURN) }}>Cancel</button>}</div>
      </form>

      <div className="card"><h2 className="text-lg font-semibold text-gray-900 mb-4">Return results</h2>{returns.length === 0 ? <p className="text-gray-400">No returns calculated.</p> : <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-gray-500 border-b border-gray-200"><th className="py-2 font-medium">Taxpayer</th><th className="font-medium">Year</th><th className="font-medium">AGI</th><th className="font-medium">Taxable</th><th className="font-medium">Federal tax</th><th className="font-medium">Refund / due</th><th className="font-medium">State refund / due</th><th></th></tr></thead><tbody>{returns.map(r => <tr key={r.id} className="border-b border-gray-50 hover:bg-gray-50/50"><td className="py-3 text-gray-900">{r.taxpayer_name}</td><td className="text-gray-600">{r.tax_year}</td><td className="text-gray-600">{money(r.adjusted_gross_income)}</td><td className="text-gray-600">{money(r.taxable_income)}</td><td className="text-gray-600">{money(r.federal_tax)}</td><td className={r.federal_refund_or_due < 0 ? 'text-red-600 font-medium' : 'text-emerald-600 font-medium'}>{money(r.federal_refund_or_due)}</td><td className={r.state_refund_or_due < 0 ? 'text-red-600 font-medium' : 'text-emerald-600 font-medium'}>{money(r.state_refund_or_due)}</td><td><button className="text-primary-600 hover:text-primary-700 font-medium" onClick={() => editReturn(r)}>Edit</button></td></tr>)}</tbody></table></div>}</div>

      <div className="card"><h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2 mb-3"><Building2 size={20} className="text-primary-600" /> Corporate tax</h2><p className="text-gray-500 mb-4">Corporate returns will use financial results from Accounting in the next phase.</p>{businesses.length === 0 ? <p className="text-sm text-gray-400">Create a business in Accounting to begin.</p> : businesses.map(b => <div key={b.id} className="py-2 border-b border-gray-100 last:border-0 text-gray-700">{b.legal_name} · {b.entity_type.replaceAll('_', ' ')}</div>)}</div>
    </div>
  )
}
