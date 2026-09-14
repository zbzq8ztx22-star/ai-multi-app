import { useEffect, useState } from 'react'
import { BarChart3, Receipt } from 'lucide-react'
import { apiGet } from '../api'

const year = new Date().getFullYear()
const money = value => Number(value || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export default function FinancialReports({ businessId }) {
  const [dates, setDates] = useState({ start: `${year}-01-01`, end: `${year}-12-31`, asOf: `${year}-12-31` })
  const [profitLoss, setProfitLoss] = useState(null)
  const [balanceSheet, setBalanceSheet] = useState(null)
  const [corpTax, setCorpTax] = useState(null)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      const [pl, bs, ct] = await Promise.all([
        apiGet(`/api/accounting/reports/profit-loss?business_id=${businessId}&start_date=${dates.start}&end_date=${dates.end}`),
        apiGet(`/api/accounting/reports/balance-sheet?business_id=${businessId}&as_of=${dates.asOf}`),
        apiGet(`/api/accounting/reports/corporate-tax?business_id=${businessId}&start_date=${dates.start}&end_date=${dates.end}`),
      ])
      setProfitLoss(pl); setBalanceSheet(bs); setCorpTax(ct); setError('')
    } catch (err) { setError(err.message) }
  }
  useEffect(() => { load() }, [businessId])

  const section = (title, rows, total) => <div><h3 className="font-medium text-gray-900 mb-2">{title}</h3>{rows.map(row => <div key={row.id} className="flex justify-between text-sm py-1"><span className="text-gray-700">{row.code} · {row.name}</span><span className="text-gray-600">{money(row.amount)}</span></div>)}<div className="flex justify-between font-semibold text-gray-900 border-t border-gray-200 mt-2 pt-2"><span>Total {title}</span><span>{money(total)}</span></div></div>

  return <div className="card space-y-5">
    <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2"><BarChart3 size={20} className="text-primary-600" /> Financial statements</h2>
    <div className="grid grid-cols-4 gap-3"><input className="input-field" type="date" value={dates.start} onChange={e => setDates({ ...dates, start: e.target.value })} /><input className="input-field" type="date" value={dates.end} onChange={e => setDates({ ...dates, end: e.target.value })} /><input className="input-field" type="date" value={dates.asOf} onChange={e => setDates({ ...dates, asOf: e.target.value })} /><button className="btn-primary" onClick={load}>Run reports</button></div>
    {error && <p className="text-red-600 text-sm">{error}</p>}
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
      {profitLoss && <div className="space-y-4"><h2 className="text-xl font-bold text-gray-900">Profit & Loss</h2>{section('Revenue', profitLoss.revenue, profitLoss.total_revenue)}{section('Expenses', profitLoss.expenses, profitLoss.total_expenses)}<div className="flex justify-between text-lg font-bold text-gray-900 border-t border-gray-300 pt-3"><span>Net income</span><span>{money(profitLoss.net_income)}</span></div></div>}
      {balanceSheet && <div className="space-y-4"><h2 className="text-xl font-bold text-gray-900">Balance Sheet</h2>{section('Assets', balanceSheet.assets, balanceSheet.total_assets)}{section('Liabilities', balanceSheet.liabilities, balanceSheet.total_liabilities)}{section('Equity', balanceSheet.equity, balanceSheet.total_equity)}<div className="flex justify-between text-sm text-gray-600"><span>Current earnings</span><span>{money(balanceSheet.current_earnings)}</span></div><p className={`text-sm font-medium ${balanceSheet.balanced ? 'text-emerald-600' : 'text-red-600'}`}>{balanceSheet.balanced ? 'Balance sheet is balanced' : 'Balance sheet is out of balance'}</p></div>}
    </div>
    {corpTax && <div className="border-t border-gray-200 pt-4 space-y-2"><h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2"><Receipt size={18} className="text-primary-600" /> Corporate tax estimate</h2><div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm"><div><span className="text-gray-500 block">Revenue</span><span className="text-gray-900">{money(corpTax.total_revenue)}</span></div><div><span className="text-gray-500 block">Expenses</span><span className="text-gray-900">{money(corpTax.total_expenses)}</span></div><div><span className="text-gray-500 block">Net income</span><span className="text-gray-900">{money(corpTax.net_income)}</span></div><div><span className="text-gray-500 block">Taxable income</span><span className="text-gray-900">{money(corpTax.taxable_income)}</span></div></div><div className="flex justify-between font-semibold text-gray-900"><span>Federal tax estimate ({(corpTax.rate * 100).toFixed(0)}%)</span><span>{money(corpTax.federal_tax_estimate)}</span></div><p className="text-xs text-gray-400">{corpTax.disclaimer}</p></div>}
  </div>
}
