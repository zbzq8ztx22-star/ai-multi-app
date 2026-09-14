import { useEffect, useState } from 'react'
import { Plus, Receipt, Printer, Ban } from 'lucide-react'
import { apiGet, apiPost, apiPut } from '../api'

const today = () => new Date().toISOString().slice(0, 10)
const money = value => Number(value || 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export default function AccountingOperations({ businessId, accounts, onPosted }) {
  const [contacts, setContacts] = useState([])
  const [invoices, setInvoices] = useState([])
  const [expenses, setExpenses] = useState([])
  const [contact, setContact] = useState({ name: '', contact_type: 'customer', email: '' })
  const [invoice, setInvoice] = useState({ customer_id: '', invoice_number: '', issue_date: today(), due_date: today(), description: '', amount: '', receivable_account_id: '', revenue_account_id: '' })
  const [payment, setPayment] = useState({ invoice_id: '', payment_date: today(), amount: '', cash_account_id: '' })
  const [expense, setExpense] = useState({ vendor_id: '', expense_date: today(), reference: '', description: '', amount: '', expense_account_id: '', payment_account_id: '' })
  const [error, setError] = useState('')

  const load = async () => {
    const [people, bills, costs] = await Promise.all([
      apiGet(`/api/accounting/contacts?business_id=${businessId}`), apiGet(`/api/accounting/invoices?business_id=${businessId}`), apiGet(`/api/accounting/expenses?business_id=${businessId}`),
    ])
    setContacts(people); setInvoices(bills); setExpenses(costs); setError('')
  }
  useEffect(() => { load().catch(err => setError(err.message)) }, [businessId])

  const submit = handler => async event => {
    event.preventDefault()
    try { await handler(); await load(); await onPosted(); setError('') } catch (err) { setError(err.message) }
  }
  const customers = contacts.filter(c => c.contact_type !== 'vendor')
  const vendors = contacts.filter(c => c.contact_type !== 'customer')
  const assets = accounts.filter(a => a.account_type === 'asset')
  const revenues = accounts.filter(a => a.account_type === 'revenue')
  const expenseAccounts = accounts.filter(a => a.account_type === 'expense')
  const paymentAccounts = accounts.filter(a => ['asset', 'liability'].includes(a.account_type))
  const openInvoices = invoices.filter(i => i.status === 'open')

  return <div className="space-y-6">
    {error && <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700">{error}</div>}
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <form className="card space-y-3" onSubmit={submit(async () => { await apiPost('/api/accounting/contacts', { ...contact, business_id: businessId }); setContact({ name: '', contact_type: 'customer', email: '' }) })}>
        <h2 className="font-semibold text-gray-900">Customers & vendors</h2><div className="grid grid-cols-3 gap-2"><input className="input-field" required placeholder="Name" value={contact.name} onChange={e => setContact({ ...contact, name: e.target.value })} /><select className="input-field" value={contact.contact_type} onChange={e => setContact({ ...contact, contact_type: e.target.value })}><option value="customer">Customer</option><option value="vendor">Vendor</option><option value="both">Both</option></select><input className="input-field" type="email" placeholder="Email" value={contact.email} onChange={e => setContact({ ...contact, email: e.target.value })} /></div><button className="btn-primary flex gap-2"><Plus size={16} /> Add contact</button>
        <div className="space-y-1">{contacts.map(c => <div key={c.id} className="flex justify-between text-sm p-2.5 bg-gray-50 rounded-lg border border-gray-100"><span className="text-gray-900">{c.name}</span><span className="badge badge-neutral capitalize">{c.contact_type}</span></div>)}</div>
      </form>

      <form className="card space-y-3" onSubmit={submit(async () => { await apiPost('/api/accounting/invoices', { ...invoice, business_id: businessId }); setInvoice({ ...invoice, customer_id: '', invoice_number: '', description: '', amount: '' }) })}>
        <h2 className="font-semibold text-gray-900">New invoice</h2><div className="grid grid-cols-2 gap-2"><select className="input-field" required value={invoice.customer_id} onChange={e => setInvoice({ ...invoice, customer_id: e.target.value })}><option value="">Customer</option>{customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select><input className="input-field" required placeholder="Invoice number" value={invoice.invoice_number} onChange={e => setInvoice({ ...invoice, invoice_number: e.target.value })} /><input className="input-field" type="date" required value={invoice.issue_date} onChange={e => setInvoice({ ...invoice, issue_date: e.target.value })} /><input className="input-field" type="date" required value={invoice.due_date} onChange={e => setInvoice({ ...invoice, due_date: e.target.value })} /><input className="input-field" required placeholder="Description" value={invoice.description} onChange={e => setInvoice({ ...invoice, description: e.target.value })} /><input className="input-field" type="number" min="0.01" step="0.01" required placeholder="Amount" value={invoice.amount} onChange={e => setInvoice({ ...invoice, amount: e.target.value })} /><select className="input-field" required value={invoice.receivable_account_id} onChange={e => setInvoice({ ...invoice, receivable_account_id: e.target.value })}><option value="">A/R account</option>{assets.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select><select className="input-field" required value={invoice.revenue_account_id} onChange={e => setInvoice({ ...invoice, revenue_account_id: e.target.value })}><option value="">Revenue account</option>{revenues.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select></div><button className="btn-primary">Create & post invoice</button>
      </form>

      <form className="card space-y-3" onSubmit={submit(async () => { await apiPost('/api/accounting/payments', payment); setPayment({ ...payment, invoice_id: '', amount: '' }) })}>
        <h2 className="font-semibold text-gray-900">Receive payment</h2><select className="input-field" required value={payment.invoice_id} onChange={e => setPayment({ ...payment, invoice_id: e.target.value })}><option value="">Open invoice</option>{openInvoices.map(i => <option key={i.id} value={i.id}>{i.invoice_number} · {i.customer_name} · {money(i.amount - i.amount_paid)}</option>)}</select><div className="grid grid-cols-3 gap-2"><input className="input-field" type="date" required value={payment.payment_date} onChange={e => setPayment({ ...payment, payment_date: e.target.value })} /><input className="input-field" type="number" min="0.01" step="0.01" required placeholder="Amount" value={payment.amount} onChange={e => setPayment({ ...payment, amount: e.target.value })} /><select className="input-field" required value={payment.cash_account_id} onChange={e => setPayment({ ...payment, cash_account_id: e.target.value })}><option value="">Cash account</option>{assets.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select></div><button className="btn-primary">Post payment</button>
      </form>

      <form className="card space-y-3" onSubmit={submit(async () => { await apiPost('/api/accounting/expenses', { ...expense, business_id: businessId }); setExpense({ ...expense, vendor_id: '', reference: '', description: '', amount: '' }) })}>
        <h2 className="font-semibold text-gray-900">Record expense</h2><div className="grid grid-cols-2 gap-2"><select className="input-field" value={expense.vendor_id} onChange={e => setExpense({ ...expense, vendor_id: e.target.value })}><option value="">No vendor</option>{vendors.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select><input className="input-field" type="date" required value={expense.expense_date} onChange={e => setExpense({ ...expense, expense_date: e.target.value })} /><input className="input-field" placeholder="Reference" value={expense.reference} onChange={e => setExpense({ ...expense, reference: e.target.value })} /><input className="input-field" required placeholder="Description" value={expense.description} onChange={e => setExpense({ ...expense, description: e.target.value })} /><input className="input-field" type="number" min="0.01" step="0.01" required placeholder="Amount" value={expense.amount} onChange={e => setExpense({ ...expense, amount: e.target.value })} /><select className="input-field" required value={expense.expense_account_id} onChange={e => setExpense({ ...expense, expense_account_id: e.target.value })}><option value="">Expense account</option>{expenseAccounts.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select><select className="input-field" required value={expense.payment_account_id} onChange={e => setExpense({ ...expense, payment_account_id: e.target.value })}><option value="">Paid from / payable</option>{paymentAccounts.map(a => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}</select></div><button className="btn-primary">Record & post expense</button>
      </form>
    </div>
    <div className="card"><h2 className="font-semibold text-gray-900 flex gap-2 mb-3"><Receipt size={18} className="text-primary-600" /> Recent operations</h2>{invoices.map(i => <div key={`i${i.id}`} className="flex justify-between py-2.5 border-b border-gray-50 last:border-0"><div className="flex items-center gap-2"><span className="text-gray-900">Invoice {i.invoice_number} · {i.customer_name}</span><a href={`/api/accounting/invoices/${i.id}/print`} target="_blank" rel="noopener" className="text-gray-400 hover:text-primary-600 no-print"><Printer size={14} /></a>{i.status === 'open' && <button onClick={async () => { try { await apiPut(`/api/accounting/invoices/${i.id}/void`); await load() } catch (err) { setError(err.message) } }} className="text-gray-400 hover:text-red-600 no-print"><Ban size={14} /></button>}</div><span className="text-gray-600">{money(i.amount)} · <span className={`badge ${i.status === 'open' ? 'badge-warning' : 'badge-neutral'}`}>{i.status}</span></span></div>)}{expenses.map(e => <div key={`e${e.id}`} className="flex justify-between py-2.5 border-b border-gray-50 last:border-0"><span className="text-gray-900">Expense · {e.description}</span><span className="text-gray-600">{money(e.amount)}</span></div>)}</div>
  </div>
}
