import { useEffect, useState } from 'react'
import { BarChart3, BookOpen, Building2, Plus, RefreshCw } from 'lucide-react'
import { apiGet, apiPost } from '../api'
import AccountingOperations from './AccountingOperations'
import Budgets from './Budgets'
import FinancialReports from './FinancialReports'

const EMPTY_BUSINESS = { legal_name: '', dba_name: '', entity_type: 'llc', ein_last4: '', formation_state: '', fiscal_year_end: '12-31', accounting_method: 'cash' }
const EMPTY_ACCOUNT = { code: '', name: '', account_type: 'asset' }
const emptyEntry = () => ({ entry_date: new Date().toISOString().slice(0, 10), reference: '', description: '', lines: [{ account_id: '', debit: '', credit: '' }, { account_id: '', debit: '', credit: '' }] })
const money = value => Number(value || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export default function Accounting() {
  const [businesses, setBusinesses] = useState([])
  const [businessId, setBusinessId] = useState('')
  const [accounts, setAccounts] = useState([])
  const [entries, setEntries] = useState([])
  const [trialBalance, setTrialBalance] = useState(null)
  const [businessForm, setBusinessForm] = useState(EMPTY_BUSINESS)
  const [accountForm, setAccountForm] = useState(EMPTY_ACCOUNT)
  const [entryForm, setEntryForm] = useState(emptyEntry)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const loadBusinesses = async () => {
    const data = await apiGet('/api/entities/businesses')
    setBusinesses(data)
    if (!businessId && data.length) setBusinessId(String(data[0].id))
  }

  const loadAccounting = async id => {
    if (!id) { setAccounts([]); setEntries([]); setTrialBalance(null); return }
    const [chart, journal, balance] = await Promise.all([
      apiGet(`/api/accounting/accounts?business_id=${id}`), apiGet(`/api/accounting/entries?business_id=${id}`), apiGet(`/api/accounting/trial-balance?business_id=${id}`),
    ])
    setAccounts(chart); setEntries(journal); setTrialBalance(balance)
  }

  const refresh = async () => {
    setLoading(true)
    try { await loadBusinesses(); if (businessId) await loadAccounting(businessId); setError('') } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  useEffect(() => { loadBusinesses().catch(err => setError(err.message)) }, [])
  useEffect(() => { loadAccounting(businessId).catch(err => setError(err.message)) }, [businessId])

  const submitBusiness = async event => {
    event.preventDefault(); setLoading(true)
    try { const created = await apiPost('/api/entities/businesses', businessForm); setBusinessForm(EMPTY_BUSINESS); await loadBusinesses(); setBusinessId(String(created.id)); setError('') } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  const submitAccount = async event => {
    event.preventDefault(); setLoading(true)
    try { await apiPost('/api/accounting/accounts', { ...accountForm, business_id: businessId }); setAccountForm(EMPTY_ACCOUNT); await loadAccounting(businessId); setError('') } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  const updateLine = (index, field, value) => setEntryForm(form => ({ ...form, lines: form.lines.map((line, i) => i === index ? { ...line, [field]: value } : line) }))
  const addLine = () => setEntryForm(form => ({ ...form, lines: [...form.lines, { account_id: '', debit: '', credit: '' }] }))

  const submitEntry = async event => {
    event.preventDefault(); setLoading(true)
    try { await apiPost('/api/accounting/entries', { ...entryForm, business_id: businessId }); setEntryForm(emptyEntry()); await loadAccounting(businessId); setError('') } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <div className="flex items-center justify-between"><div><h1 className="text-2xl font-bold flex items-center gap-2"><BookOpen className="text-primary-400" /> Accounting</h1><p className="text-gray-400 mt-1">Double-entry accounting by business</p></div><button onClick={refresh} className="btn-secondary flex items-center gap-2"><RefreshCw size={16} /> Refresh</button></div>
      {error && <div className="p-4 bg-red-900/20 border border-red-800 rounded-lg text-red-200">{error}</div>}

      <form onSubmit={submitBusiness} className="card space-y-4">
        <h2 className="text-lg font-semibold flex items-center gap-2"><Building2 size={20} /> Add business</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3"><input className="input-field" required placeholder="Legal name" value={businessForm.legal_name} onChange={e => setBusinessForm({ ...businessForm, legal_name: e.target.value })} /><input className="input-field" placeholder="DBA name" value={businessForm.dba_name} onChange={e => setBusinessForm({ ...businessForm, dba_name: e.target.value })} /><select className="input-field" value={businessForm.entity_type} onChange={e => setBusinessForm({ ...businessForm, entity_type: e.target.value })}><option value="sole_proprietorship">Sole proprietorship</option><option value="llc">LLC</option><option value="partnership">Partnership</option><option value="s_corp">S Corporation</option><option value="c_corp">C Corporation</option><option value="nonprofit">Nonprofit</option></select><button className="btn-primary" disabled={loading}>Add business</button></div>
      </form>

      <div className="card"><label className="text-sm text-gray-400 block mb-2">Active business</label><select className="input-field max-w-md" value={businessId} onChange={e => setBusinessId(e.target.value)}><option value="">Select a business</option>{businesses.map(b => <option key={b.id} value={b.id}>{b.legal_name}</option>)}</select></div>

      {businessId && <>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <form onSubmit={submitAccount} className="card space-y-4"><h2 className="text-lg font-semibold">Chart of accounts</h2><div className="grid grid-cols-3 gap-3"><input className="input-field" required placeholder="Code, e.g. 1000" value={accountForm.code} onChange={e => setAccountForm({ ...accountForm, code: e.target.value })} /><input className="input-field" required placeholder="Account name" value={accountForm.name} onChange={e => setAccountForm({ ...accountForm, name: e.target.value })} /><select className="input-field" value={accountForm.account_type} onChange={e => setAccountForm({ ...accountForm, account_type: e.target.value })}>{['asset', 'liability', 'equity', 'revenue', 'expense'].map(type => <option key={type}>{type}</option>)}</select></div><button className="btn-primary flex items-center gap-2"><Plus size={16} /> Add account</button><div className="space-y-2">{accounts.map(a => <div key={a.id} className="flex justify-between p-2 bg-gray-800 rounded"><span>{a.code} · {a.name}</span><span className="text-gray-400 capitalize">{a.account_type}</span></div>)}</div></form>

          <form onSubmit={submitEntry} className="card space-y-4"><h2 className="text-lg font-semibold">New journal entry</h2><div className="grid grid-cols-3 gap-3"><input className="input-field" type="date" required value={entryForm.entry_date} onChange={e => setEntryForm({ ...entryForm, entry_date: e.target.value })} /><input className="input-field" placeholder="Reference" value={entryForm.reference} onChange={e => setEntryForm({ ...entryForm, reference: e.target.value })} /><input className="input-field" required placeholder="Description" value={entryForm.description} onChange={e => setEntryForm({ ...entryForm, description: e.target.value })} /></div>{entryForm.lines.map((line, index) => <div key={index} className="grid grid-cols-3 gap-3"><select className="input-field" required value={line.account_id} onChange={e => updateLine(index, 'account_id', e.target.value)}><option value="">Account</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select><input className="input-field" type="number" min="0" step="0.01" placeholder="Debit" value={line.debit} onChange={e => updateLine(index, 'debit', e.target.value)} /><input className="input-field" type="number" min="0" step="0.01" placeholder="Credit" value={line.credit} onChange={e => updateLine(index, 'credit', e.target.value)} /></div>)}<div className="flex gap-2"><button type="button" className="btn-secondary" onClick={addLine}>Add line</button><button className="btn-primary" disabled={accounts.length < 2}>Post balanced entry</button></div></form>
        </div>

        <AccountingOperations businessId={businessId} accounts={accounts} onPosted={() => loadAccounting(businessId)} />

        <FinancialReports businessId={businessId} />

        <Budgets businessId={businessId} accounts={accounts} />

        <div className="card"><h2 className="text-lg font-semibold flex items-center gap-2 mb-4"><BarChart3 size={20} /> Trial balance</h2>{trialBalance && <><div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-gray-400 border-b border-gray-700"><th className="py-2">Account</th><th>Type</th><th className="text-right">Debits</th><th className="text-right">Credits</th></tr></thead><tbody>{trialBalance.accounts.map(a => <tr key={a.id} className="border-b border-gray-800"><td className="py-2">{a.code} · {a.name}</td><td className="capitalize">{a.account_type}</td><td className="text-right">{money(a.debits)}</td><td className="text-right">{money(a.credits)}</td></tr>)}</tbody><tfoot><tr className="font-bold"><td className="pt-3" colSpan="2">Totals</td><td className="pt-3 text-right">{money(trialBalance.total_debits)}</td><td className="pt-3 text-right">{money(trialBalance.total_credits)}</td></tr></tfoot></table></div><p className={`mt-3 ${trialBalance.balanced ? 'text-green-400' : 'text-red-400'}`}>{trialBalance.balanced ? 'Books are balanced' : 'Books are out of balance'}</p></>}</div>

        <div className="card"><h2 className="text-lg font-semibold mb-4">General journal</h2>{entries.length === 0 ? <p className="text-gray-400">No journal entries yet.</p> : entries.map(entry => <div key={entry.id} className="mb-4 p-3 bg-gray-800 rounded-lg"><div className="flex justify-between"><strong>{entry.entry_date} · {entry.description}</strong><span className="text-gray-400">{entry.reference}</span></div>{entry.lines.map(line => <div key={line.id} className="grid grid-cols-3 text-sm mt-2"><span>{line.account_code} · {line.account_name}</span><span className="text-right">Debit {money(line.debit)}</span><span className="text-right">Credit {money(line.credit)}</span></div>)}</div>)}</div>
      </>}
    </div>
  )
}
