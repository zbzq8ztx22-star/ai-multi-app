import { useState } from 'react'
import { Upload, Loader2, FileText, Sparkles, Trash2 } from 'lucide-react'
import { apiPost } from '../api'

export default function Docs() {
  const [file, setFile] = useState(null)
  const [fileName, setFileName] = useState('')
  const [analysis, setAnalysis] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleFileSelect = (e) => {
    const selectedFile = e.target.files[0]
    if (selectedFile) {
      setFile(selectedFile)
      setFileName(selectedFile.name)
      setAnalysis('')
      setError('')
    }
  }

  const analyzeDocument = async () => {
    if (!file) return

    setLoading(true)
    setAnalysis('')
    setError('')
    const formData = new FormData()
    formData.append('document', file)

    try {
      const data = await apiPost('/api/docs', formData)
      const result = typeof data.analysis === 'string' ? data.analysis : ''
      if (!result) {
        throw new Error('No analysis returned from the server.')
      }
      setAnalysis(result)
    } catch (error) {
      setError(error?.message || 'Error analyzing document. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const clearFile = () => {
    setFile(null)
    setFileName('')
    setAnalysis('')
    setError('')
  }

  return (
    <div className="flex flex-col h-full bg-gray-50">
      <div className="p-6 border-b border-gray-200 bg-gray-50">
        <h2 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <FileText size={28} className="text-primary-600" aria-hidden="true" />
          Document Analysis
        </h2>
        <p className="text-gray-500 mt-1">Upload documents for AI-powered analysis</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <div className="card space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Upload Document</label>
            <div className="border-2 border-dashed border-gray-300 rounded-xl p-6 text-center hover:border-primary-400 hover:bg-primary-50/30 transition-colors">
              <input
                type="file"
                onChange={handleFileSelect}
                accept=".pdf,.doc,.docx,.txt,.md"
                className="hidden"
                id="doc-upload"
                aria-label="Select a document"
              />
              <label
                htmlFor="doc-upload"
                className="cursor-pointer flex flex-col items-center gap-3"
              >
                <div className="w-14 h-14 bg-primary-50 rounded-full flex items-center justify-center">
                  <Upload size={28} className="text-primary-500" aria-hidden="true" />
                </div>
                <div>
                  <p className="font-medium text-gray-900">Click to upload</p>
                  <p className="text-sm text-gray-500">PDF, DOC, DOCX, TXT, MD (max 16 MB)</p>
                </div>
              </label>
            </div>
          </div>

          {fileName && (
            <div className="flex items-center justify-between bg-gray-50 rounded-lg p-3 border border-gray-100">
              <div className="flex items-center gap-3">
                <FileText size={20} className="text-primary-600" aria-hidden="true" />
                <span className="truncate text-gray-700" title={fileName}>{fileName}</span>
              </div>
              <button
                onClick={clearFile}
                className="p-2 hover:bg-gray-200 rounded-lg transition-colors text-gray-400 hover:text-red-600"
                aria-label="Remove selected document"
                title="Remove selected document"
              >
                <Trash2 size={18} aria-hidden="true" />
              </button>
            </div>
          )}

          <button
            onClick={analyzeDocument}
            disabled={loading || !file}
            className="btn-primary w-full flex items-center justify-center gap-2"
            aria-label="Analyze document"
            title="Analyze document"
          >
            {loading ? (
              <Loader2 className="animate-spin" size={20} aria-hidden="true" />
            ) : (
              <Sparkles size={20} aria-hidden="true" />
            )}
            Analyze Document
          </button>
        </div>

        {error && (
          <div className="card bg-red-50 border-red-200">
            <h3 className="text-lg font-semibold text-red-700 mb-2">Analysis Error</h3>
            <p className="text-red-600 whitespace-pre-wrap">{error}</p>
          </div>
        )}

        {analysis && (
          <div className="card">
            <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <Sparkles size={20} className="text-primary-600" aria-hidden="true" />
              Analysis Results
            </h3>
            <p className="text-gray-700 whitespace-pre-wrap leading-relaxed">{analysis}</p>
          </div>
        )}
      </div>
    </div>
  )
}
