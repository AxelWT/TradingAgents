import { useState } from 'react'
import { Loader2 } from 'lucide-react'

const LLM_PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'google', label: 'Google' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'ollama', label: 'Ollama' },
]

const ANALYST_OPTIONS = [
  { value: 'market', label: 'Market Analyst' },
  { value: 'social', label: 'Sentiment Analyst' },
  { value: 'news', label: 'News Analyst' },
  { value: 'fundamentals', label: 'Fundamentals Analyst' },
]

const DEPTH_OPTIONS = [
  { value: 1, label: 'Quick (1 round)' },
  { value: 2, label: 'Standard (2 rounds)' },
  { value: 3, label: 'Deep (3 rounds)' },
  { value: 4, label: 'Very Deep (4 rounds)' },
]

interface ConfigFormProps {
  onSubmit: (config: {
    ticker: string
    trade_date: string
    asset_type: string
    analysts: string[]
    research_depth: number
    llm_provider: string
    backend_url?: string
    quick_think_llm?: string
    deep_think_llm?: string
    output_language: string
    google_thinking_level?: string
    openai_reasoning_effort?: string
    anthropic_effort?: string
  }) => void
}

export default function ConfigForm({ onSubmit }: ConfigFormProps) {
  const [ticker, setTicker] = useState('')
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().split('T')[0])
  const [analysts, setAnalysts] = useState<string[]>(['market', 'social', 'news', 'fundamentals'])
  const [researchDepth, setResearchDepth] = useState(2)
  const [llmProvider, setLlmProvider] = useState('openai')
  const [outputLanguage, setOutputLanguage] = useState('English')
  const [loading, setLoading] = useState(false)

  const toggleAnalyst = (value: string) => {
    setAnalysts((prev) =>
      prev.includes(value) ? prev.filter((a) => a !== value) : [...prev, value]
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    onSubmit({
      ticker,
      trade_date: tradeDate,
      asset_type: 'stock',
      analysts,
      research_depth: researchDepth,
      llm_provider: llmProvider,
      output_language: outputLanguage,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Ticker Symbol <span className="text-red-400">*</span>
        </label>
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
          placeholder="e.g. AAPL, 0700.HK, BTC-USD"
          required
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">Analysis Date</label>
        <input
          type="date"
          value={tradeDate}
          onChange={(e) => setTradeDate(e.target.value)}
          className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
          required
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-3">Analyst Team</label>
        <div className="grid grid-cols-2 gap-3">
          {ANALYST_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => toggleAnalyst(value)}
              className={`px-4 py-3 rounded-lg border text-sm font-medium transition-colors ${
                analysts.includes(value)
                  ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-400'
                  : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-3">Research Depth</label>
        <div className="grid grid-cols-2 gap-3">
          {DEPTH_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setResearchDepth(value)}
              className={`px-4 py-3 rounded-lg border text-sm font-medium transition-colors ${
                researchDepth === value
                  ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-400'
                  : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">LLM Provider</label>
        <select
          value={llmProvider}
          onChange={(e) => setLlmProvider(e.target.value)}
          className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
        >
          {LLM_PROVIDERS.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">Output Language</label>
        <select
          value={outputLanguage}
          onChange={(e) => setOutputLanguage(e.target.value)}
          className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
        >
          <option value="English">English</option>
          <option value="Chinese">Chinese</option>
          <option value="Japanese">Japanese</option>
          <option value="Spanish">Spanish</option>
        </select>
      </div>

      <button
        type="submit"
        disabled={loading || analysts.length === 0}
        className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
      >
        {loading ? (
          <>
            <Loader2 className="w-5 h-5 animate-spin" />
            Starting Analysis...
          </>
        ) : (
          'Start Analysis'
        )}
      </button>
    </form>
  )
}
