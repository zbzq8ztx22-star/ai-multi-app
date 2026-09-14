import { useEffect, useRef } from 'react'
import { X, Printer, DollarSign, Calendar, User, Briefcase, Clock, FileText } from 'lucide-react'

function formatCurrency(value) {
  const num = Number(value)
  if (Number.isNaN(num)) return '-'
  return num.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export default function PayslipDetail({ payslip, employeeName, periodDesc, payType, onClose }) {
  const panelRef = useRef(null)

  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  const handlePrint = () => {
    window.print()
  }

  const deductions = payslip.deductions || []

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 print:p-0 print:bg-white print:static"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
      role="dialog"
      aria-modal="true"
      aria-label={`Payslip for ${employeeName}`}
    >
      <div
        ref={panelRef}
        className="bg-gray-50 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto border border-gray-200 print:max-h-none print:shadow-none print:border-0 print:bg-white print:text-black"
      >
        <div className="p-6 border-b border-gray-200 flex items-center justify-between print:hidden">
          <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
            <FileText size={22} className="text-primary-600" aria-hidden="true" />
            Payslip Detail
          </h2>
          <div className="flex items-center gap-2">
            <button
              onClick={handlePrint}
              className="btn-secondary flex items-center gap-2 text-sm"
              aria-label="Print payslip"
              title="Print"
            >
              <Printer size={16} aria-hidden="true" /> Print
            </button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600"
              aria-label="Close"
              title="Close"
            >
              <X size={20} aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="p-6 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 print:grid-cols-2">
            <div className="card-flat space-y-2 print:border print:border-gray-300">
              <div className="flex items-center gap-2 text-gray-500 print:text-gray-600">
                <User size={16} aria-hidden="true" /> Employee
              </div>
              <p className="text-lg font-semibold text-gray-900">{employeeName}</p>
            </div>
            <div className="card-flat space-y-2 print:border print:border-gray-300">
              <div className="flex items-center gap-2 text-gray-500 print:text-gray-600">
                <Calendar size={16} aria-hidden="true" /> Pay Period
              </div>
              <p className="text-lg font-semibold text-gray-900">{periodDesc}</p>
            </div>
            <div className="card-flat space-y-2 print:border print:border-gray-300">
              <div className="flex items-center gap-2 text-gray-500 print:text-gray-600">
                <Briefcase size={16} aria-hidden="true" /> Pay Type
              </div>
              <p className="text-lg font-semibold text-gray-900 capitalize">{payType || '-'}</p>
            </div>
            <div className="card-flat space-y-2 print:border print:border-gray-300">
              <div className="flex items-center gap-2 text-gray-500 print:text-gray-600">
                <Clock size={16} aria-hidden="true" /> Hours
              </div>
              <p className="text-lg font-semibold text-gray-900">
                {payslip.regular_hours} regular / {payslip.overtime_hours} overtime
              </p>
            </div>
          </div>

          <div className="card-flat print:border print:border-gray-300">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <DollarSign size={20} className="text-primary-600 print:text-black" aria-hidden="true" />
              Earnings & Deductions
            </h3>
            <div className="space-y-3">
              <div className="flex justify-between border-b border-gray-100 print:border-gray-300 pb-2">
                <span className="text-gray-500 print:text-gray-600">Gross Pay</span>
                <span className="font-semibold text-gray-900">{formatCurrency(payslip.gross_pay)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 print:text-gray-600">Federal Tax</span>
                <span className="text-gray-700">{formatCurrency(payslip.federal_tax)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 print:text-gray-600">State Tax</span>
                <span className="text-gray-700">{formatCurrency(payslip.state_tax)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 print:text-gray-600">FICA (Social Security)</span>
                <span className="text-gray-700">{formatCurrency(payslip.fica_tax)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500 print:text-gray-600">Medicare</span>
                <span className="text-gray-700">{formatCurrency(payslip.medicare_tax)}</span>
              </div>
              {deductions.length > 0 && (
                <div className="pt-2 border-t border-gray-100 print:border-gray-300">
                  <p className="text-sm text-gray-500 print:text-gray-600 mb-2">Other Deductions</p>
                  {deductions.map((ded, idx) => (
                    <div key={idx} className="flex justify-between text-sm">
                      <span className="text-gray-700">{ded.name} <span className="text-gray-400">({ded.category})</span></span>
                      <span className="text-gray-700">{formatCurrency(ded.amount)}</span>
                    </div>
                  ))}
                  <div className="flex justify-between pt-2 mt-2 border-t border-gray-100 print:border-gray-300">
                    <span className="text-gray-500 print:text-gray-600">Total Other Deductions</span>
                    <span className="text-gray-700">{formatCurrency(payslip.other_deductions)}</span>
                  </div>
                </div>
              )}
              <div className="flex justify-between border-t border-gray-200 print:border-gray-300 pt-3 text-lg font-bold text-gray-900">
                <span>Net Pay</span>
                <span>{formatCurrency(payslip.net_pay)}</span>
              </div>
            </div>
          </div>

          <p className="text-xs text-gray-400 print:text-gray-400 text-center">
            This is a simplified calculation for demonstration purposes and is not tax advice.
          </p>
        </div>
      </div>
    </div>
  )
}
