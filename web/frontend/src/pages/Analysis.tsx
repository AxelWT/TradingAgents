import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { analysisApi } from '../api/analysis'
import { useAnalysisStore } from '../stores/analysisStore'
import { useWebSocket } from '../hooks/useWebSocket'
import ConfigForm from '../components/analysis/ConfigForm'
import AnalysisDashboard from '../components/analysis/AnalysisDashboard'
import { ArrowLeft } from 'lucide-react'

export default function Analysis() {
  const { taskId: existingTaskId } = useParams()
  const navigate = useNavigate()
  const [showDashboard, setShowDashboard] = useState(!!existingTaskId)
  const store = useAnalysisStore()

  useWebSocket(store.taskId)

  const handleSubmit = async (config: {
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
  }) => {
    try {
      const task = await analysisApi.create(config)
      store.startAnalysis(task.id)
      setShowDashboard(true)
    } catch (err) {
      console.error('Failed to create analysis:', err)
    }
  }

  if (existingTaskId && !store.taskId) {
    store.startAnalysis(existingTaskId)
    if (!showDashboard) setShowDashboard(true)
  }

  return (
    <div className="h-full flex flex-col">
      <div className="p-6 border-b border-gray-800 flex items-center gap-4">
        <button
          onClick={() => navigate('/')}
          className="p-2 text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <h1 className="text-2xl font-bold text-white">
          {showDashboard ? 'Analysis Running' : 'New Analysis'}
        </h1>
        {store.taskId && showDashboard && (
          <span className="text-sm text-gray-500 ml-auto">Task: {store.taskId.slice(0, 8)}...</span>
        )}
      </div>

      <div className="flex-1 overflow-auto">
        {showDashboard ? (
          <AnalysisDashboard />
        ) : (
          <div className="max-w-2xl mx-auto p-6">
            <ConfigForm onSubmit={handleSubmit} />
          </div>
        )}
      </div>
    </div>
  )
}
