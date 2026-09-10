import { useEffect, useState } from 'react'
import { Target, Plus, Trash2 } from 'lucide-react'
import { apiGet, apiPost, apiPut, apiDelete } from '../api'

const year = new Date().getFullYear()
const money = value => Number(value || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export default function Budgets({ businessId, accounts }) {
  const [fiscalYear, setFiscalYear] = useState(year)
  const [budgets, setBudgets] = useState([])
  const [report, setReport] = useState(null)
  const [form, setForm] = useState({ account_id: '', budgeted_amount: '' })
  const [error, setError] = useState('')

  const load = async () => {
    try {
      const [list, vs] = await Promise.all([
        apiGet(`/api/accounting/budgets?business_id=${businessId}&fiscal_year=${fiscalYear}`),
        apiGet(`/api/accounting/reports/budget-vs-actual?business_id=${businessId}&fiscal_year=${fiscalYear}`),
      ])
      setBudgets(list); setReport(vs); setError('')
    } catch (err) { setError(err.message) }
  }
  useEffect(() => { load() }, [businessId, fiscalYear])

  const submit = async event => {
    event.preventDefault()
    try {
      await apiPost('/api/accounting/budgets', { business_id: businessId, account_id: form.account_id, fiscal_year: fiscalYear, period: 'annual', budgeted_amount: form.budgeted_amount })
      setForm({ account_id: '', budgeted_amount: '' }); await load()
    } catch (err) { setError(err.message) }
  }

  const remove = async id => {
    try { await apiDelete(`/api/accounting/budgets/${id}`); await load() } catch (err) { setError(err.message) }
  }

  const reportAccounts = accounts.filter(a => ['revenue', 'expense'].includes(a.account_type))

  return <div className="card space-y-5">
    <h2 className="text-lg font-semibold flex items-center gap-2"><Target size={20} /> Budgets</h2>
    <div className="flex items-center gap-3">
      <label className="text-sm text-gray-400">Fiscal year</label>
      <input className="input-field w-32" type="number" min="2000" max="2100" value={fiscalYear} onChange={e => setFiscalYear(e.target.value)} />
    </div>
    {error && <p className="text-red-400">{error}</p>}

    <form onSubmit={submit} className="grid grid-cols-3 gap-3">
      <select className="input-field" required value={form.account_id} onChange={e => setForm({ ...form, account_id: e.target.value })}>
        <option value="">Account</option>
        {reportAccounts.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
      </select>
      <input className="input-field" type="number" min="0" step="0.01" required placeholder="Budgeted amount" value={form.budgeted_amount} onChange={e => setForm({ ...form, budgeted_amount: e.target.value })} />
      <button className="btn-primary flex items-center gap-2"><Plus size={16} /> Add budget</button>
    </form>

    {report && report.lines.length > 0 && <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="text-left text-gray-400 border-b border-gray-700"><th className="py-2">Account</th><th>Type</th><th className="text-right">Budgeted</th><th className="text-right">Actual</th><th className="text-right">Variance</th><th></th></tr></thead>
        <tbody>
          {report.lines.map(line => <tr key={line.account_id} className="border-b border-gray-800">
            <td className="py-2">{line.account_code} · {line.account_name}</td>
            <td className="capitalize">{line.account_type}</td>
            <td className="text-right">{money(line.budgeted)}</td>
            <td className="text-right">{money(line.actual)}</td>
            <td className={`text-right ${line.variance < 0 ? 'text-red-400' : 'text-green-400'}`}>{money(line.variance)}</td>
            <td className="text-right">{budgets.find(b => b.account_id === line.account_id) && <button onClick={() => remove(budgets.find(b => b.account_id === line.account_id).id)} className="text-gray-500 hover:text-red-400"><Trash2 size={16} /></button>}</td>
          </tr>)}
        </tbody>
        <tfoot><tr className="font-bold"><td className="pt-3" colSpan="2">Totals</td><td className="pt-3 text-right">{money(report.total_budgeted)}</td><td className="pt-3 text-right">{money(report.total_actual)}</td><td className="pt-3 text-right">{money(report.total_variance)}</td><td></td></tr></tfoot>
      </table>
    </div>}
    {report && report.lines.length === 0 && <p className="text-gray-400 text-sm">No budgets set for {fiscalYear}. Add a budget for a revenue or expense account above.</p>}
  </div>
}
