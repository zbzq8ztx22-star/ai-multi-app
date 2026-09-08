import { useState, useRef } from 'react'
import { Upload, Loader2, Image as ImageIcon, Sparkles } from 'lucide-react'

export default function Vision() {
  const [image, setImage] = useState(null)
  const [preview, setPreview] = useState(null)
  const [analysis, setAnalysis] = useState('')
  const [loading, setLoading] = useState(false)
  const fileInputRef = useRef(null)

  const handleFileSelect = (e) => {
    const file = e.target.files[0]
    if (file && file.type.startsWith('image/')) {
      setImage(file)
      setPreview(URL.createObjectURL(file))
      setAnalysis('')
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file && file.type.startsWith('image/')) {
      setImage(file)
      setPreview(URL.createObjectURL(file))
      setAnalysis('')
    }
  }

  const analyzeImage = async () => {
    if (!image) return

    setLoading(true)
    const formData = new FormData()
    formData.append('image', image)

    try {
      const response = await fetch('/api/vision', {
        method: 'POST',
        body: formData
      })
      
      const data = await response.json()
      setAnalysis(data.analysis)
    } catch (error) {
      setAnalysis('Error analyzing image. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-6 border-b border-gray-700">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <ImageIcon size={28} />
          Image Analysis
        </h2>
        <p className="text-gray-400 mt-1">Upload an image and I'll analyze it for you</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
          className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
            preview ? 'border-gray-600' : 'border-gray-700 hover:border-primary-500'
          }`}
        >
          {preview ? (
            <div className="space-y-4">
              <img
                src={preview}
                alt="Preview"
                className="max-h-96 mx-auto rounded-lg"
              />
              <div className="flex gap-3 justify-center">
                <button
                  onClick={analyzeImage}
                  disabled={loading}
                  className="btn-primary flex items-center gap-2"
                >
                  {loading ? (
                    <Loader2 className="animate-spin" size={20} />
                  ) : (
                    <Sparkles size={20} />
                  )}
                  Analyze Image
                </button>
                <button
                  onClick={() => {
                    setImage(null)
                    setPreview(null)
                    setAnalysis('')
                  }}
                  className="btn-secondary"
                >
                  Clear
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="w-16 h-16 mx-auto bg-gray-700 rounded-full flex items-center justify-center">
                <Upload size={32} className="text-gray-400" />
              </div>
              <div>
                <p className="text-lg font-medium">Drop an image here</p>
                <p className="text-gray-400">or click to browse</p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleFileSelect}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="btn-primary"
              >
                Select Image
              </button>
            </div>
          )}
        </div>

        {analysis && (
          <div className="mt-6 card">
            <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
              <Sparkles size={20} className="text-primary-400" />
              Analysis Results
            </h3>
            <p className="text-gray-300 whitespace-pre-wrap">{analysis}</p>
          </div>
        )}
      </div>
    </div>
  )
}
