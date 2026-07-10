import { useState } from 'react'
import { Loader2, AlertCircle, Search, CheckCircle2 } from 'lucide-react'
import Select from '../ui/Select'
import { tickerApi, type TickerCandidate } from '../../api/ticker'

const LLM_PROVIDERS = [
  { value: 'deepseek', label: 'DeepSeek' },
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

const OUTPUT_LANGUAGES = [
  { value: 'Chinese', label: 'Chinese' },
  { value: 'English', label: 'English' },
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
  }) => void | Promise<void>
}

export default function ConfigForm({ onSubmit }: ConfigFormProps) {
  const [ticker, setTicker] = useState('')
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().split('T')[0])
  const [analysts, setAnalysts] = useState<string[]>(['market', 'social', 'news', 'fundamentals'])
  const [researchDepth, setResearchDepth] = useState(2)
  const [llmProvider, setLlmProvider] = useState('deepseek')
  const [outputLanguage, setOutputLanguage] = useState('Chinese')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [looking, setLooking] = useState(false)
  const [candidates, setCandidates] = useState<TickerCandidate[]>([])
  const [lookupError, setLookupError] = useState('')
  const [hasSearched, setHasSearched] = useState(false)

  const toggleAnalyst = (value: string) => {
    setAnalysts((prev) =>
      prev.includes(value) ? prev.filter((a) => a !== value) : [...prev, value]
    )
  }

  const handleLookup = async () => {
    const query = companyName.trim()
    if (!query || looking) return
    setLooking(true)
    setLookupError('')
    setCandidates([])
    setHasSearched(true)
    try {
      const { candidates: results } = await tickerApi.lookup(query)
      setCandidates(results)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Lookup failed'
      setLookupError(msg)
    } finally {
      setLooking(false)
    }
  }

  const pickCandidate = (candidate: TickerCandidate) => {
    setTicker(candidate.ticker.toUpperCase())
    setCandidates([])
    setCompanyName('')
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await onSubmit({
        ticker,
        trade_date: tradeDate,
        asset_type: 'stock',
        analysts,
        research_depth: researchDepth,
        llm_provider: llmProvider,
        output_language: outputLanguage,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to start analysis'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      {error && (
        <div className="flex items-center gap-2 p-3 bg-down/10 border border-down/20 rounded-lg text-down text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}
      <div>
        <label className="block text-sm font-medium text-text-secondary mb-2">
          Ticker Symbol <span className="text-down">*</span>
        </label>
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          className="w-full px-4 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
          placeholder="e.g. AAPL, 0700.HK, BTC-USD"
          required
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-text-secondary mb-2">
          Search by company name
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleLookup()
              }
            }}
            className="flex-1 px-4 py-2.5 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
            placeholder="e.g. Apple, 腾讯, Tesla, 茅台"
          />
          <button
            type="button"
            onClick={handleLookup}
            disabled={looking || !companyName.trim()}
            className="px-4 py-2.5 bg-surface-2 hover:bg-surface border border-border-subtle hover:border-accent/50 disabled:opacity-50 disabled:cursor-not-allowed text-text-primary text-sm font-medium rounded-lg transition-colors flex items-center gap-2 whitespace-nowrap"
          >
            {looking ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Search className="w-4 h-4" />
            )}
            Search
          </button>
        </div>
        {lookupError && (
          <p className="mt-2 text-sm text-down">{lookupError}</p>
        )}
        {candidates.length > 0 && (
          <div className="mt-2 space-y-1.5">
            {candidates.map((candidate, index) => (
              <button
                key={`${candidate.ticker}-${index}`}
                type="button"
                onClick={() => pickCandidate(candidate)}
                className="w-full flex items-center justify-between gap-3 px-3 py-2 bg-surface-2 hover:bg-surface border border-border-subtle hover:border-accent/50 rounded-lg text-left transition-colors"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-medium text-text-primary shrink-0" style={{ fontFamily: 'var(--font-mono)' }}>
                    {candidate.ticker}
                  </span>
                  <span className="text-text-secondary text-sm truncate">
                    {candidate.name}
                  </span>
                  {candidate.exchange && (
                    <span className="text-text-faint text-xs shrink-0 hidden sm:inline">
                      · {candidate.exchange}
                    </span>
                  )}
                </div>
                {candidate.validated ? (
                  <span className="flex items-center gap-1 text-accent text-xs shrink-0">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Verified
                  </span>
                ) : (
                  <span className="text-text-faint text-xs shrink-0">Unverified</span>
                )}
              </button>
            ))}
          </div>
        )}
        {!looking && !lookupError && hasSearched && candidates.length === 0 && (
          <p className="mt-2 text-xs text-text-faint">
            No results — try a more complete name or the English name.
          </p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-text-secondary mb-2">Analysis Date</label>
        <input
          type="date"
          value={tradeDate}
          onChange={(e) => setTradeDate(e.target.value)}
          className="w-full px-4 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
          required
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-text-secondary mb-3">Analyst Team</label>
        <div className="grid grid-cols-2 gap-2 md:gap-3">
          {ANALYST_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => toggleAnalyst(value)}
              className={`px-3 py-2.5 md:px-4 md:py-3 rounded-lg border text-sm font-medium transition-colors ${
                analysts.includes(value)
                  ? 'bg-accent/10 border-accent/50 text-accent'
                  : 'bg-surface-2 border-border-subtle text-text-secondary hover:border-border-strong'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-text-secondary mb-3">Research Depth</label>
        <div className="grid grid-cols-2 gap-2 md:gap-3">
          {DEPTH_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setResearchDepth(value)}
              className={`px-3 py-2.5 md:px-4 md:py-3 rounded-lg border text-sm font-medium transition-colors ${
                researchDepth === value
                  ? 'bg-accent/10 border-accent/50 text-accent'
                  : 'bg-surface-2 border-border-subtle text-text-secondary hover:border-border-strong'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-text-secondary mb-2">LLM Provider</label>
        <Select
          value={llmProvider}
          options={LLM_PROVIDERS}
          onChange={setLlmProvider}
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-text-secondary mb-2">Output Language</label>
        <Select
          value={outputLanguage}
          options={OUTPUT_LANGUAGES}
          onChange={setOutputLanguage}
        />
      </div>

      <button
        type="submit"
        disabled={loading || analysts.length === 0}
        className="w-full py-3 bg-gradient-to-r from-accent to-accent-2 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed text-bg font-medium rounded-lg transition-opacity flex items-center justify-center gap-2"
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
