import { useState, useEffect } from 'react'
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

  const taskId = useAnalysisStore((s) => s.taskId)
  const startAnalysis = useAnalysisStore((s) => s.startAnalysis)
  const reset = useAnalysisStore((s) => s.reset)

  useWebSocket(taskId)

  useEffect(() => {
    if (existingTaskId) {
      startAnalysis(existingTaskId)
      setShowDashboard(true)
      analysisApi
        .get(existingTaskId)
        .then((task) => {
          if (task.status === 'completed' || task.status === 'failed') {
            useAnalysisStore.setState({
              status: task.status,
              signal: task.signal,
              finalReport: task.final_report,
              error: task.error_message,
              reportSections: task.agent_reports || {},
            })
          }
        })
        .catch((err) => console.error('Failed to load task:', err))
    } else {
      reset()
      setShowDashboard(false)
    }
  }, [existingTaskId, startAnalysis, reset])

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
    const task = await analysisApi.create(config)
    startAnalysis(task.id)
    setShowDashboard(true)
  }

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 md:p-6 border-b border-gray-800 flex items-center gap-4">
        <button
          onClick={() => navigate('/')}
          className="p-2 text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <h1 className="text-xl md:text-2xl font-bold text-white">
          {showDashboard ? 'Analysis Running' : 'New Analysis'}
        </h1>
        {taskId && showDashboard && (
          <span className="text-sm text-gray-500 ml-auto hidden sm:inline">Task: {taskId.slice(0, 8)}...</span>
        )}
      </div>

      <div className="flex-1 overflow-auto">
        {showDashboard ? (
          <AnalysisDashboard />
        ) : (
          <div className="max-w-2xl mx-auto p-4 md:p-6">
            <ConfigForm onSubmit={handleSubmit} />
          </div>
        )}
      </div>
    </div>
  )
}
