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
    <div className="flex flex-col h-full">
      <div className="p-6 border-b border-gray-700">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <FileText size={28} aria-hidden="true" />
          Document Analysis
        </h2>
        <p className="text-gray-400 mt-1">Upload documents for AI-powered analysis</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <div className="card space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">Upload Document</label>
            <div className="border-2 border-dashed border-gray-700 rounded-lg p-6 text-center hover:border-primary-500 transition-colors">
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
                <Upload size={32} className="text-gray-400" aria-hidden="true" />
                <div>
                  <p className="font-medium">Click to upload</p>
                  <p className="text-sm text-gray-400">PDF, DOC, DOCX, TXT, MD</p>
                </div>
              </label>
            </div>
          </div>

          {fileName && (
            <div className="flex items-center justify-between bg-gray-700 rounded-lg p-3">
              <div className="flex items-center gap-3">
                <FileText size={20} className="text-primary-400" aria-hidden="true" />
                <span className="truncate" title={fileName}>{fileName}</span>
              </div>
              <button
                onClick={clearFile}
                className="p-2 hover:bg-gray-600 rounded-lg transition-colors"
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
          <div className="card bg-red-900/20 border border-red-800">
            <h3 className="text-lg font-semibold text-red-300 mb-2">Analysis Error</h3>
            <p className="text-red-200 whitespace-pre-wrap">{error}</p>
          </div>
        )}

        {analysis && (
          <div className="card">
            <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
              <Sparkles size={20} className="text-primary-400" aria-hidden="true" />
              Analysis Results
            </h3>
            <div className="prose prose-invert max-w-none">
              <p className="text-gray-300 whitespace-pre-wrap">{analysis}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
