import { useState } from 'react'
import { Code, Loader2, Copy, Check, Play } from 'lucide-react'
import { apiPost } from '../api'

export default function CodeGen() {
  const [prompt, setPrompt] = useState('')
  const [language, setLanguage] = useState('python')
  const [generatedCode, setGeneratedCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  const languages = [
    'python', 'javascript', 'typescript', 'java', 'cpp', 'go', 'rust', 'sql'
  ]

  const generateCode = async () => {
    const trimmed = prompt.trim()
    if (!trimmed) return

    setLoading(true)
    setError('')
    setGeneratedCode('')

    try {
      const data = await apiPost('/api/code', { prompt: trimmed, language })
      const result = typeof data.code === 'string' ? data.code : ''
      if (!result) {
        throw new Error('No code was returned from the server.')
      }
      setGeneratedCode(result)
    } catch (error) {
      setError(error?.message || 'Error generating code. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const copyToClipboard = () => {
    if (!generatedCode) return
    navigator.clipboard.writeText(generatedCode)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-6 border-b border-gray-700">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <Code size={28} aria-hidden="true" />
          Code Generation
        </h2>
        <p className="text-gray-400 mt-1">Describe what you need and I'll write the code</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <div className="card space-y-4">
          <div>
            <label htmlFor="language-select" className="block text-sm font-medium mb-2">Programming Language</label>
            <select
              id="language-select"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="w-full input-field"
              aria-label="Programming language"
            >
              {languages.map(lang => (
                <option key={lang} value={lang}>{lang}</option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="code-prompt" className="block text-sm font-medium mb-2">Describe your code</label>
            <textarea
              id="code-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g., Create a function that sorts an array using quicksort algorithm"
              className="w-full input-field h-32 resize-none"
              aria-label="Code description"
            />
          </div>

          <button
            onClick={generateCode}
            disabled={loading || !prompt.trim()}
            className="btn-primary w-full flex items-center justify-center gap-2"
            aria-label="Generate code"
            title="Generate code"
          >
            {loading ? (
              <Loader2 className="animate-spin" size={20} aria-hidden="true" />
            ) : (
              <Play size={20} aria-hidden="true" />
            )}
            Generate Code
          </button>
        </div>

        {error && (
          <div className="card bg-red-900/20 border border-red-800">
            <h3 className="text-lg font-semibold text-red-300 mb-2">Generation Error</h3>
            <p className="text-red-200 whitespace-pre-wrap">{error}</p>
          </div>
        )}

        {generatedCode && (
          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-semibold">Generated Code</h3>
              <button
                onClick={copyToClipboard}
                className="btn-secondary flex items-center gap-2 text-sm"
                aria-label="Copy generated code to clipboard"
                title="Copy generated code to clipboard"
              >
                {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <pre className="bg-gray-900 rounded-lg p-4 overflow-x-auto text-sm" tabIndex="0" aria-label={`Generated ${language} code`}>
              <code>{generatedCode}</code>
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
