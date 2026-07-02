import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { reportsApi } from '../api/reports'
import { AnalysisTask } from '../api/analysis'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft, Download, TrendingUp, Clock, FileText } from 'lucide-react'

export default function ReportDetail() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<AnalysisTask | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (taskId) loadReport()
  }, [taskId])

  const loadReport = async () => {
    try {
      const data = await reportsApi.get(taskId!)
      setTask(data)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async () => {
    if (!taskId || !task) return
    try {
      const content = await reportsApi.download(taskId)
      const blob = new Blob([content], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report_${task.ticker}_${task.trade_date}.md`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // ignore
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        Loading report...
      </div>
    )
  }

  if (!task) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-500">
        <FileText className="w-12 h-12 mb-4 text-gray-600" />
        <p>Report not found</p>
        <Link to="/reports" className="text-emerald-400 hover:text-emerald-300 mt-4">
          Back to Reports
        </Link>
      </div>
    )
  }

  const signalColor: Record<string, string> = {
    Buy: 'text-emerald-400',
    Hold: 'text-yellow-400',
    Sell: 'text-red-400',
  }

  return (
    <div className="h-full flex flex-col">
      <div className="p-6 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/reports')}
              className="p-2 text-gray-400 hover:text-white transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div>
              <div className="flex items-center gap-3">
                <TrendingUp className="w-5 h-5 text-emerald-400" />
                <h1 className="text-2xl font-bold text-white">{task.ticker}</h1>
                {task.signal && (
                  <span
                    className={`text-lg font-bold ${signalColor[task.signal] || 'text-gray-400'}`}
                  >
                    {task.signal}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
                <Clock className="w-3.5 h-3.5" />
                <span>{task.trade_date}</span>
                {task.completed_at && (
                  <>
                    <span>|</span>
                    <span>Completed {new Date(task.completed_at).toLocaleString()}</span>
                  </>
                )}
              </div>
            </div>
          </div>

          <button
            onClick={handleDownload}
            className="flex items-center gap-2 px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-300 hover:border-emerald-500/50 hover:text-emerald-400 transition-colors"
          >
            <Download className="w-4 h-4" />
            Download
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-8">
        {task.agent_reports && Object.keys(task.agent_reports).length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-semibold text-gray-300 mb-6">Agent Reports</h2>
            <div className="space-y-6">
              {Object.entries(task.agent_reports).map(([section, content]) => {
                const titles: Record<string, string> = {
                  market_report: 'Market Analysis',
                  sentiment_report: 'Social Sentiment',
                  news_report: 'News Analysis',
                  fundamentals_report: 'Fundamentals Analysis',
                  investment_plan: 'Research Team Decision',
                  trader_investment_plan: 'Trading Team Plan',
                  final_trade_decision: 'Portfolio Management Decision',
                }
                return (
                  <div
                    key={section}
                    className="bg-gray-900 border border-gray-800 rounded-xl p-6"
                  >
                    <h3 className="text-md font-semibold text-emerald-400 mb-4">
                      {titles[section] || section}
                    </h3>
                    <div className="prose prose-invert prose-sm max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {content}
                      </ReactMarkdown>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {task.final_report && (
          <div>
            <h2 className="text-lg font-semibold text-gray-300 mb-6">Final Decision</h2>
            <div className="bg-gray-900 border border-emerald-500/20 rounded-xl p-6">
              <div className="prose prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {task.final_report}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
