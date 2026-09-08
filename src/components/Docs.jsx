import { useState } from 'react'
import { Upload, Loader2, FileText, Sparkles, Trash2 } from 'lucide-react'

export default function Docs() {
  const [file, setFile] = useState(null)
  const [fileName, setFileName] = useState('')
  const [analysis, setAnalysis] = useState('')
  const [loading, setLoading] = useState(false)

  const handleFileSelect = (e) => {
    const selectedFile = e.target.files[0]
    if (selectedFile) {
      setFile(selectedFile)
      setFileName(selectedFile.name)
      setAnalysis('')
    }
  }

  const analyzeDocument = async () => {
    if (!file) return

    setLoading(true)
    const formData = new FormData()
    formData.append('document', file)

    try {
      const response = await fetch('/api/docs', {
        method: 'POST',
        body: formData
      })
      
      const data = await response.json()
      setAnalysis(data.analysis)
    } catch (error) {
      setAnalysis('Error analyzing document. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const clearFile = () => {
    setFile(null)
    setFileName('')
    setAnalysis('')
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-6 border-b border-gray-700">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <FileText size={28} />
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
              />
              <label
                htmlFor="doc-upload"
                className="cursor-pointer flex flex-col items-center gap-3"
              >
                <Upload size={32} className="text-gray-400" />
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
                <FileText size={20} className="text-primary-400" />
                <span className="truncate">{fileName}</span>
              </div>
              <button
                onClick={clearFile}
                className="p-2 hover:bg-gray-600 rounded-lg transition-colors"
              >
                <Trash2 size={18} />
              </button>
            </div>
          )}

          <button
            onClick={analyzeDocument}
            disabled={loading || !file}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {loading ? (
              <Loader2 className="animate-spin" size={20} />
            ) : (
              <Sparkles size={20} />
            )}
            Analyze Document
          </button>
        </div>

        {analysis && (
          <div className="card">
            <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
              <Sparkles size={20} className="text-primary-400" />
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
