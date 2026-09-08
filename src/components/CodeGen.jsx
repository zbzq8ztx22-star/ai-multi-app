import { useState } from 'react'
import { Code, Loader2, Copy, Check, Play } from 'lucide-react'

export default function CodeGen() {
  const [prompt, setPrompt] = useState('')
  const [language, setLanguage] = useState('python')
  const [generatedCode, setGeneratedCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  const languages = [
    'python', 'javascript', 'typescript', 'java', 'cpp', 'go', 'rust', 'sql'
  ]

  const generateCode = async () => {
    if (!prompt.trim()) return

    setLoading(true)
    try {
      const response = await fetch('/api/code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, language })
      })
      
      const data = await response.json()
      setGeneratedCode(data.code)
    } catch (error) {
      setGeneratedCode('// Error generating code. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const copyToClipboard = () => {
    navigator.clipboard.writeText(generatedCode)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-6 border-b border-gray-700">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <Code size={28} />
          Code Generation
        </h2>
        <p className="text-gray-400 mt-1">Describe what you need and I'll write the code</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <div className="card space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">Programming Language</label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="w-full input-field"
            >
              {languages.map(lang => (
                <option key={lang} value={lang}>{lang}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Describe your code</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g., Create a function that sorts an array using quicksort algorithm"
              className="w-full input-field h-32 resize-none"
            />
          </div>

          <button
            onClick={generateCode}
            disabled={loading || !prompt.trim()}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {loading ? (
              <Loader2 className="animate-spin" size={20} />
            ) : (
              <Play size={20} />
            )}
            Generate Code
          </button>
        </div>

        {generatedCode && (
          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-semibold">Generated Code</h3>
              <button
                onClick={copyToClipboard}
                className="btn-secondary flex items-center gap-2 text-sm"
              >
                {copied ? <Check size={16} /> : <Copy size={16} />}
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <pre className="bg-gray-900 rounded-lg p-4 overflow-x-auto text-sm">
              <code>{generatedCode}</code>
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
