import { useEffect, useRef, useState } from 'react'
import { Loader2, Send, Plus, Trash2, RefreshCw, Bot, User, Briefcase, Calendar, Receipt, DollarSign, FileText, Eye } from 'lucide-react'
import { apiGet, apiPost, apiDelete } from '../api'
import PayslipDetail from './PayslipDetail'

const SECTIONS = [
  { id: 'employees', label: 'Employees', icon: Briefcase },
  { id: 'periods', label: 'Periods', icon: Calendar },
  { id: 'payslips', label: 'Payslips', icon: Receipt },
  { id: 'reports', label: 'Reports', icon: FileText },
  { id: 'assistant', label: 'Assistant', icon: Bot },
]

const EMPTY_EMPLOYEE = {
  name: '',
  position: '',
  pay_type: 'hourly',
  pay_frequency: 'biweekly',
  rate: '',
  state: '',
  filing_status: 'single',
  federal_withholding: '',
  dependents: '',
  other_income: '',
  w4_deductions: '',
  multiple_jobs: false,
}

const EMPTY_PERIOD = {
  start_date: '',
  end_date: '',
  pay_date: '',
  status: 'open',
}

const EMPTY_PAYSLIP = {
  employee_id: '',
  period_id: '',
  regular_hours: '',
  overtime_hours: '',
  deductions: [],
}

const EMPTY_DEDUCTION = {
  name: '',
  amount: '',
  category: 'other',
}

const SESSION_ID_KEY = 'payroll_assistant_session_id'

function getOrCreateSessionId() {
  let id = sessionStorage.getItem(SESSION_ID_KEY)
  if (!id) {
    id = crypto.randomUUID
      ? crypto.randomUUID()
      : Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
    sessionStorage.setItem(SESSION_ID_KEY, id)
  }
  return id
}

function saveSessionId(id) {
  if (id) sessionStorage.setItem(SESSION_ID_KEY, id)
}

function formatCurrency(value) {
  const num = Number(value)
  if (Number.isNaN(num)) return '-'
  return num.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export default function Payroll() {
  const [activeSection, setActiveSection] = useState('employees')
  const [employees, setEmployees] = useState([])
  const [periods, setPeriods] = useState([])
  const [payslips, setPayslips] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [employeeForm, setEmployeeForm] = useState(EMPTY_EMPLOYEE)
  const [periodForm, setPeriodForm] = useState(EMPTY_PERIOD)
  const [payslipForm, setPayslipForm] = useState(EMPTY_PAYSLIP)

  const [assistantMessages, setAssistantMessages] = useState([
    { role: 'assistant', content: 'Hi! I can help with payroll questions, list employees, or explain a payslip.' }
  ])
  const [assistantInput, setAssistantInput] = useState('')
  const [assistantLoading, setAssistantLoading] = useState(false)
  const [assistantSessionId, setAssistantSessionId] = useState(() => getOrCreateSessionId())

  const [reportPeriodId, setReportPeriodId] = useState('')
  const [report, setReport] = useState(null)
  const [reportLoading, setReportLoading] = useState(false)

  const [selectedPayslip, setSelectedPayslip] = useState(null)

  const messagesEndRef = useRef(null)

  const refreshData = async () => {
    setLoading(true)
    setError('')
    try {
      const [emps, pers, slips] = await Promise.all([
        apiGet('/api/payroll/employees'),
        apiGet('/api/payroll/pay-periods'),
        apiGet('/api/payroll/payslips'),
      ])
      setEmployees(emps)
      setPeriods(pers)
      setPayslips(slips)
    } catch (err) {
      setError(err?.message || 'Failed to load payroll data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshData()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [assistantMessages])

  const getEmployeeName = (id) => {
    const emp = employees.find(e => e.id === id)
    return emp ? emp.name : `Employee #${id}`
  }

  const getPeriodDesc = (id) => {
    const per = periods.find(p => p.id === id)
    return per ? `${per.start_date} to ${per.end_date}` : `Period #${id}`
  }

  const showError = (msg) => setError(msg)
  const clearError = () => setError('')

  const handleCreateEmployee = async (e) => {
    e.preventDefault()
    clearError()
    try {
      await apiPost('/api/payroll/employees', {
        ...employeeForm,
        rate: parseFloat(employeeForm.rate),
        federal_withholding: parseFloat(employeeForm.federal_withholding || 0),
        dependents: parseInt(employeeForm.dependents || 0, 10),
        other_income: parseFloat(employeeForm.other_income || 0),
        w4_deductions: parseFloat(employeeForm.w4_deductions || 0),
        multiple_jobs: employeeForm.multiple_jobs,
      })
      setEmployeeForm(EMPTY_EMPLOYEE)
      await refreshData()
    } catch (err) {
      showError(err?.message || 'Failed to create employee.')
    }
  }

  const handleDeleteEmployee = async (id) => {
    if (!window.confirm('Are you sure you want to delete this employee?')) return
    clearError()
    try {
      await apiDelete(`/api/payroll/employees/${id}`)
      await refreshData()
    } catch (err) {
      showError(err?.message || 'Failed to delete employee.')
    }
  }

  const handleCreatePeriod = async (e) => {
    e.preventDefault()
    clearError()
    const payload = { ...periodForm }
    if (!payload.pay_date) delete payload.pay_date
    try {
      await apiPost('/api/payroll/pay-periods', payload)
      setPeriodForm(EMPTY_PERIOD)
      await refreshData()
    } catch (err) {
      showError(err?.message || 'Failed to create pay period.')
    }
  }

  const handleDeletePeriod = async (id) => {
    if (!window.confirm('Are you sure you want to delete this pay period?')) return
    clearError()
    try {
      await apiDelete(`/api/payroll/pay-periods/${id}`)
      await refreshData()
    } catch (err) {
      showError(err?.message || 'Failed to delete pay period.')
    }
  }

  const handleCreatePayslip = async (e) => {
    e.preventDefault()
    clearError()
    const deductions = payslipForm.deductions
      .filter(d => d.name.trim() && d.amount !== '')
      .map(d => ({ ...d, amount: parseFloat(d.amount) }))
    try {
      await apiPost('/api/payroll/payslips', {
        employee_id: parseInt(payslipForm.employee_id, 10),
        period_id: parseInt(payslipForm.period_id, 10),
        regular_hours: parseFloat(payslipForm.regular_hours || 0),
        overtime_hours: parseFloat(payslipForm.overtime_hours || 0),
        deductions,
      })
      setPayslipForm(EMPTY_PAYSLIP)
      await refreshData()
    } catch (err) {
      showError(err?.message || 'Failed to create payslip.')
    }
  }

  const addDeduction = () => {
    setPayslipForm(prev => ({
      ...prev,
      deductions: [...prev.deductions, { ...EMPTY_DEDUCTION }],
    }))
  }

  const updateDeduction = (idx, field, value) => {
    setPayslipForm(prev => {
      const updated = [...prev.deductions]
      updated[idx] = { ...updated[idx], [field]: value }
      return { ...prev, deductions: updated }
    })
  }

  const removeDeduction = (idx) => {
    setPayslipForm(prev => ({
      ...prev,
      deductions: prev.deductions.filter((_, i) => i !== idx),
    }))
  }

  const handleDeletePayslip = async (id) => {
    if (!window.confirm('Are you sure you want to delete this payslip?')) return
    clearError()
    try {
      await apiDelete(`/api/payroll/payslips/${id}`)
      await refreshData()
    } catch (err) {
      showError(err?.message || 'Failed to delete payslip.')
    }
  }

  const handleLoadReport = async (e) => {
    e.preventDefault()
    if (!reportPeriodId) return
    setReportLoading(true)
    clearError()
    setReport(null)
    try {
      const data = await apiGet(`/api/payroll/reports/${reportPeriodId}`)
      setReport(data)
    } catch (err) {
      showError(err?.message || 'Failed to load report.')
    } finally {
      setReportLoading(false)
    }
  }

  const handleAssistantSubmit = async (e) => {
    e.preventDefault()
    const trimmed = assistantInput.trim()
    if (!trimmed || assistantLoading) return

    setAssistantMessages(prev => [...prev, { role: 'user', content: trimmed }])
    setAssistantInput('')
    setAssistantLoading(true)
    clearError()

    try {
      const data = await apiPost('/api/payroll/assistant', {
        message: trimmed,
        session_id: assistantSessionId,
      })
      if (data.session_id) {
        setAssistantSessionId(data.session_id)
        saveSessionId(data.session_id)
      }
      const reply = typeof data.response === 'string' ? data.response : ''
      setAssistantMessages(prev => [...prev, { role: 'assistant', content: reply || 'No response received.' }])
    } catch (err) {
      setAssistantMessages(prev => [...prev, { role: 'assistant', content: err?.message || 'Sorry, the assistant failed to respond.' }])
    } finally {
      setAssistantLoading(false)
    }
  }

  const renderEmployees = () => (
    <div className="space-y-6">
      <form onSubmit={handleCreateEmployee} className="card space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">Add Employee</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Name</label>
            <input
              type="text"
              required
              value={employeeForm.name}
              onChange={e => setEmployeeForm({ ...employeeForm, name: e.target.value })}
              className="w-full input-field"
              placeholder="e.g. Alice Smith"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Position</label>
            <input
              type="text"
              value={employeeForm.position}
              onChange={e => setEmployeeForm({ ...employeeForm, position: e.target.value })}
              className="w-full input-field"
              placeholder="e.g. Developer"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Pay Type</label>
            <select
              value={employeeForm.pay_type}
              onChange={e => setEmployeeForm({ ...employeeForm, pay_type: e.target.value })}
              className="w-full input-field"
            >
              <option value="hourly">Hourly</option>
              <option value="salary">Salary</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Pay Frequency</label>
            <select
              value={employeeForm.pay_frequency}
              onChange={e => setEmployeeForm({ ...employeeForm, pay_frequency: e.target.value })}
              className="w-full input-field"
            >
              <option value="weekly">Weekly</option>
              <option value="biweekly">Biweekly</option>
              <option value="semimonthly">Semimonthly</option>
              <option value="monthly">Monthly</option>
              <option value="annual">Annual</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Rate</label>
            <input
              type="number"
              step="0.01"
              min="0.01"
              required
              value={employeeForm.rate}
              onChange={e => setEmployeeForm({ ...employeeForm, rate: e.target.value })}
              className="w-full input-field"
              placeholder={employeeForm.pay_type === 'hourly' ? 'Hourly rate' : 'Annual salary'}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">State (2-letter)</label>
            <input
              type="text"
              maxLength={2}
              value={employeeForm.state}
              onChange={e => setEmployeeForm({ ...employeeForm, state: e.target.value.toUpperCase() })}
              className="w-full input-field"
              placeholder="e.g. CA"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Filing Status</label>
            <select
              value={employeeForm.filing_status}
              onChange={e => setEmployeeForm({ ...employeeForm, filing_status: e.target.value })}
              className="w-full input-field"
            >
              <option value="single">Single</option>
              <option value="married">Married</option>
              <option value="hoh">Head of Household</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Extra Federal Withholding</label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={employeeForm.federal_withholding}
              onChange={e => setEmployeeForm({ ...employeeForm, federal_withholding: e.target.value })}
              className="w-full input-field"
              placeholder="Per paycheck amount"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Dependents</label>
            <input
              type="number"
              min="0"
              step="1"
              value={employeeForm.dependents}
              onChange={e => setEmployeeForm({ ...employeeForm, dependents: e.target.value })}
              className="w-full input-field"
              placeholder="Number of dependents"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Other Income (annual)</label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={employeeForm.other_income}
              onChange={e => setEmployeeForm({ ...employeeForm, other_income: e.target.value })}
              className="w-full input-field"
              placeholder="Annual other income"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">W-4 Deductions</label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={employeeForm.w4_deductions}
              onChange={e => setEmployeeForm({ ...employeeForm, w4_deductions: e.target.value })}
              className="w-full input-field"
              placeholder="Annual deductions"
            />
          </div>
          <div className="flex items-center gap-2 md:col-span-2">
            <input
              id="multiple-jobs"
              type="checkbox"
              checked={employeeForm.multiple_jobs}
              onChange={e => setEmployeeForm({ ...employeeForm, multiple_jobs: e.target.checked })}
              className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
            />
            <label htmlFor="multiple-jobs" className="text-sm font-medium">Multiple jobs (W-4 Step 2c)</label>
          </div>
        </div>
        <button type="submit" className="btn-primary flex items-center gap-2">
          <Plus size={18} /> Add Employee
        </button>
      </form>

      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Employees</h3>
        {employees.length === 0 ? (
          <p className="text-gray-500">No employees yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-gray-500 border-b border-gray-200 font-medium">
                  <th className="pb-2">Name</th>
                  <th className="pb-2">Type</th>
                  <th className="pb-2">Rate</th>
                  <th className="pb-2">State</th>
                  <th className="pb-2">Filing</th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody>
                {employees.map(emp => (
                  <tr key={emp.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                    <td className="py-2">{emp.name}</td>
                    <td className="py-2">{emp.pay_type}</td>
                    <td className="py-2">{formatCurrency(emp.rate)}</td>
                    <td className="py-2">{emp.state || '-'}</td>
                    <td className="py-2">{emp.filing_status}</td>
                    <td className="py-2 text-right">
                      <button
                        onClick={() => handleDeleteEmployee(emp.id)}
                        className="text-gray-400 hover:text-red-600"
                        aria-label={`Delete ${emp.name}`}
                        title="Delete"
                      >
                        <Trash2 size={18} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )

  const renderPeriods = () => (
    <div className="space-y-6">
      <form onSubmit={handleCreatePeriod} className="card space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">Add Pay Period</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Start Date</label>
            <input
              type="date"
              required
              value={periodForm.start_date}
              onChange={e => setPeriodForm({ ...periodForm, start_date: e.target.value })}
              className="w-full input-field"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">End Date</label>
            <input
              type="date"
              required
              value={periodForm.end_date}
              onChange={e => setPeriodForm({ ...periodForm, end_date: e.target.value })}
              className="w-full input-field"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Pay Date</label>
            <input
              type="date"
              value={periodForm.pay_date}
              onChange={e => setPeriodForm({ ...periodForm, pay_date: e.target.value })}
              className="w-full input-field"
            />
          </div>
        </div>
        <button type="submit" className="btn-primary flex items-center gap-2">
          <Plus size={18} /> Add Period
        </button>
      </form>

      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Pay Periods</h3>
        {periods.length === 0 ? (
          <p className="text-gray-500">No pay periods yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-gray-500 border-b border-gray-200 font-medium">
                  <th className="pb-2">Dates</th>
                  <th className="pb-2">Pay Date</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody>
                {periods.map(per => (
                  <tr key={per.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                    <td className="py-2">{per.start_date} to {per.end_date}</td>
                    <td className="py-2">{per.pay_date || '-'}</td>
                    <td className="py-2 capitalize">{per.status}</td>
                    <td className="py-2 text-right">
                      <button
                        onClick={() => handleDeletePeriod(per.id)}
                        className="text-gray-400 hover:text-red-600"
                        aria-label="Delete period"
                        title="Delete"
                      >
                        <Trash2 size={18} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )

  const renderPayslips = () => (
    <div className="space-y-6">
      <form onSubmit={handleCreatePayslip} className="card space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">Run Payroll</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Employee</label>
            <select
              required
              value={payslipForm.employee_id}
              onChange={e => setPayslipForm({ ...payslipForm, employee_id: e.target.value })}
              className="w-full input-field"
            >
              <option value="">Select employee</option>
              {employees.map(emp => (
                <option key={emp.id} value={emp.id}>{emp.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Pay Period</label>
            <select
              required
              value={payslipForm.period_id}
              onChange={e => setPayslipForm({ ...payslipForm, period_id: e.target.value })}
              className="w-full input-field"
            >
              <option value="">Select period</option>
              {periods.map(per => (
                <option key={per.id} value={per.id}>{per.start_date} to {per.end_date}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Regular Hours</label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={payslipForm.regular_hours}
              onChange={e => setPayslipForm({ ...payslipForm, regular_hours: e.target.value })}
              className="w-full input-field"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Overtime Hours</label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={payslipForm.overtime_hours}
              onChange={e => setPayslipForm({ ...payslipForm, overtime_hours: e.target.value })}
              className="w-full input-field"
            />
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium">Deductions</label>
            <button
              type="button"
              onClick={addDeduction}
              className="text-sm text-primary-600 hover:text-primary-700 flex items-center gap-1"
            >
              <Plus size={14} /> Add
            </button>
          </div>
          {payslipForm.deductions.map((ded, idx) => (
            <div key={idx} className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-2">
              <input
                type="text"
                placeholder="Name"
                value={ded.name}
                onChange={e => updateDeduction(idx, 'name', e.target.value)}
                className="input-field"
              />
              <input
                type="number"
                step="0.01"
                min="0"
                placeholder="Amount"
                value={ded.amount}
                onChange={e => updateDeduction(idx, 'amount', e.target.value)}
                className="input-field"
              />
              <div className="flex gap-2">
                <select
                  value={ded.category}
                  onChange={e => updateDeduction(idx, 'category', e.target.value)}
                  className="input-field flex-1"
                >
                  <option value="other">Other</option>
                  <option value="benefit">Benefit</option>
                  <option value="garnishment">Garnishment</option>
                  <option value="tax">Tax</option>
                </select>
                <button
                  type="button"
                  onClick={() => removeDeduction(idx)}
                  className="text-gray-400 hover:text-red-600 px-2"
                  aria-label="Remove deduction"
                >
                  <Trash2 size={18} />
                </button>
              </div>
            </div>
          ))}
        </div>

        <button type="submit" className="btn-primary flex items-center gap-2">
          <DollarSign size={18} /> Calculate Payslip
        </button>
      </form>

      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Payslips</h3>
        {payslips.length === 0 ? (
          <p className="text-gray-500">No payslips yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-gray-500 border-b border-gray-200 font-medium">
                  <th className="pb-2">Employee</th>
                  <th className="pb-2">Period</th>
                  <th className="pb-2">Gross</th>
                  <th className="pb-2">Taxes</th>
                  <th className="pb-2">Net</th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody>
                {payslips.map(slip => (
                  <tr key={slip.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                    <td className="py-2">{getEmployeeName(slip.employee_id)}</td>
                    <td className="py-2">{getPeriodDesc(slip.period_id)}</td>
                    <td className="py-2">{formatCurrency(slip.gross_pay)}</td>
                    <td className="py-2">{formatCurrency(slip.federal_tax + slip.state_tax + slip.fica_tax + slip.medicare_tax)}</td>
                    <td className="py-2 font-semibold">{formatCurrency(slip.net_pay)}</td>
                    <td className="py-2 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => setSelectedPayslip(slip)}
                          className="text-primary-600 hover:text-primary-700"
                          aria-label="View payslip"
                          title="View"
                        >
                          <Eye size={18} />
                        </button>
                        <button
                          onClick={() => handleDeletePayslip(slip.id)}
                          className="text-gray-400 hover:text-red-600"
                          aria-label="Delete payslip"
                          title="Delete"
                        >
                          <Trash2 size={18} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )

  const renderAssistant = () => (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-6 space-y-4" role="log" aria-live="polite" aria-label="Payroll assistant messages">
        {assistantMessages.map((msg, idx) => (
          <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'assistant' && (
              <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center flex-shrink-0" aria-hidden="true">
                <Bot size={18} />
              </div>
            )}
            <div className={`max-w-2xl rounded-2xl px-4 py-3 ${msg.role === 'user' ? 'bg-primary-600 text-white' : 'bg-gray-50 text-gray-700 border border-gray-200 shadow-sm'}`}>
              <p className="whitespace-pre-wrap">{msg.content}</p>
            </div>
            {msg.role === 'user' && (
              <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 text-gray-500" aria-hidden="true">
                <User size={18} />
              </div>
            )}
          </div>
        ))}
        {assistantLoading && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center flex-shrink-0" aria-hidden="true">
              <Bot size={18} />
            </div>
            <div className="bg-gray-50 rounded-2xl px-4 py-3 border border-gray-200 shadow-sm">
              <Loader2 className="animate-spin" size={20} aria-label="Assistant is typing" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleAssistantSubmit} className="p-6 border-t border-gray-200">
        <div className="flex gap-3">
          <input
            type="text"
            value={assistantInput}
            onChange={e => setAssistantInput(e.target.value)}
            placeholder="Ask about payroll, employees or payslips..."
            className="flex-1 input-field"
            disabled={assistantLoading}
            aria-label="Assistant message"
          />
          <button
            type="submit"
            disabled={assistantLoading || !assistantInput.trim()}
            className="btn-primary flex items-center gap-2"
            aria-label="Send"
            title="Send"
          >
            {assistantLoading ? <Loader2 className="animate-spin" size={20} aria-hidden="true" /> : <Send size={20} aria-hidden="true" />}
            Send
          </button>
        </div>
      </form>
    </div>
  )

  const renderReports = () => (
    <div className="space-y-6">
      <form onSubmit={handleLoadReport} className="card space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">Payroll Report</h3>
        <div className="flex gap-4 items-end">
          <div className="flex-1">
            <label className="block text-sm font-medium mb-1">Pay Period</label>
            <select
              value={reportPeriodId}
              onChange={e => { setReportPeriodId(e.target.value); setReport(null) }}
              className="w-full input-field"
              required
            >
              <option value="">Select a period</option>
              {periods.map(per => (
                <option key={per.id} value={per.id}>{per.start_date} to {per.end_date}</option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={reportLoading || !reportPeriodId} className="btn-primary flex items-center gap-2">
            {reportLoading ? <Loader2 className="animate-spin" size={18} /> : <FileText size={18} />}
            Load Report
          </button>
          <a
            href={reportPeriodId ? `/api/payroll/reports/${reportPeriodId}/csv` : undefined}
            className={`btn-secondary flex items-center gap-2 ${!reportPeriodId ? 'pointer-events-none opacity-50' : ''}`}
            aria-disabled={!reportPeriodId}
          >
            <FileText size={18} /> Download CSV
          </a>
        </div>
      </form>

      {report && (
        <div className="card space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-sm text-gray-500">Employees</p>
              <p className="text-xl font-bold">{report.total_employees}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Total Gross</p>
              <p className="text-xl font-bold">{formatCurrency(report.total_gross)}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Total Taxes</p>
              <p className="text-xl font-bold">{formatCurrency(report.total_taxes)}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Total Net</p>
              <p className="text-xl font-bold">{formatCurrency(report.total_net)}</p>
            </div>
          </div>

          {report.rows.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-200 font-medium">
                    <th className="pb-2">Employee</th>
                    <th className="pb-2">Gross</th>
                    <th className="pb-2">Federal</th>
                    <th className="pb-2">State</th>
                    <th className="pb-2">FICA</th>
                    <th className="pb-2">Medicare</th>
                    <th className="pb-2">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {report.rows.map((row, idx) => (
                    <tr key={idx} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                      <td className="py-2">{row.employee_name}</td>
                      <td className="py-2">{formatCurrency(row.gross_pay)}</td>
                      <td className="py-2">{formatCurrency(row.federal_tax)}</td>
                      <td className="py-2">{formatCurrency(row.state_tax)}</td>
                      <td className="py-2">{formatCurrency(row.fica_tax)}</td>
                      <td className="py-2">{formatCurrency(row.medicare_tax)}</td>
                      <td className="py-2 font-semibold">{formatCurrency(row.net_pay)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-gray-500">No payslips found for this period.</p>
          )}
        </div>
      )}
    </div>
  )

  const sections = {
    employees: renderEmployees,
    periods: renderPeriods,
    payslips: renderPayslips,
    reports: renderReports,
    assistant: renderAssistant,
  }

  const renderActiveSection = sections[activeSection] || renderEmployees

  return (
    <div className="flex h-full bg-gray-50">
      <aside className="w-48 bg-gray-50 border-r border-gray-200 p-4">
        <h2 className="text-xl font-bold text-primary-600 mb-4 flex items-center gap-2">
          <DollarSign size={24} /> Payroll
        </h2>
        <nav className="space-y-2" role="tablist" aria-label="Payroll sections">
          {SECTIONS.map(section => {
            const Icon = section.icon
            return (
              <button
                key={section.id}
                onClick={() => { setActiveSection(section.id); clearError() }}
                className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${
                  activeSection === section.id
                    ? 'bg-primary-600 text-white'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
                role="tab"
                aria-selected={activeSection === section.id}
              >
                <Icon size={18} aria-hidden="true" />
                {section.label}
              </button>
            )
          })}
        </nav>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">{SECTIONS.find(s => s.id === activeSection)?.label}</h2>
            <p className="text-gray-500 text-sm">
              {activeSection === 'employees' && 'Manage employees, pay rates and withholding.'}
              {activeSection === 'periods' && 'Create and manage pay periods.'}
              {activeSection === 'payslips' && 'Calculate and review payslips.'}
              {activeSection === 'reports' && 'View totals and download CSV for a period.'}
              {activeSection === 'assistant' && 'Ask the payroll assistant about your data.'}
            </p>
          </div>
          <button
            onClick={refreshData}
            disabled={loading}
            className="btn-secondary flex items-center gap-2 text-sm"
            aria-label="Refresh payroll data"
            title="Refresh"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
            Refresh
          </button>
        </div>

        {error && (
          <div className="mx-4 mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-red-700">{error}</p>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-6">
          {renderActiveSection()}
        </div>
      </main>

      {selectedPayslip && (
        <PayslipDetail
          payslip={selectedPayslip}
          employeeName={getEmployeeName(selectedPayslip.employee_id)}
          periodDesc={getPeriodDesc(selectedPayslip.period_id)}
          payType={employees.find(e => e.id === selectedPayslip.employee_id)?.pay_type || ''}
          onClose={() => setSelectedPayslip(null)}
        />
      )}
    </div>
  )
}
