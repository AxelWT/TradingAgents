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
      <div className="flex items-center justify-center h-full text-text-secondary">
        Loading report...
      </div>
    )
  }

  if (!task) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-text-secondary">
        <FileText className="w-12 h-12 mb-4 text-text-faint" />
        <p>Report not found</p>
        <Link to="/reports" className="text-accent hover:opacity-80 mt-4">
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
    <div className="h-full flex flex-col relative z-1">
      <div className="p-4 md:p-6 border-b border-border-subtle">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/reports')}
              className="p-2 text-text-secondary hover:text-text-primary transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div>
              <div className="flex items-center gap-3">
                <TrendingUp className="w-5 h-5 text-accent" />
                <h1 className="text-xl md:text-2xl font-bold text-text-primary" style={{ fontFamily: 'var(--font-serif)' }}>
                  {task.ticker}
                </h1>
                {task.signal && (
                  <span
                    className={`text-lg font-bold ${signalColor[task.signal] || 'text-text-secondary'}`}
                  >
                    {task.signal}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 mt-1 text-sm text-text-faint">
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
            className="flex items-center gap-2 px-4 py-2 bg-surface-2 border border-border-subtle rounded-lg text-sm text-text-secondary hover:border-accent/50 hover:text-accent transition-colors"
          >
            <Download className="w-4 h-4" />
            Download
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4 md:p-8">
        {task.agent_reports && Object.keys(task.agent_reports).length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-semibold text-text-secondary mb-6" style={{ fontFamily: 'var(--font-serif)' }}>
              Agent Reports
            </h2>
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
                    className="surface-card bg-surface border border-border-subtle rounded-xl p-4 md:p-6"
                  >
                    <h3 className="text-md font-semibold text-accent mb-4" style={{ fontFamily: 'var(--font-serif)' }}>
                      {titles[section] || section}
                    </h3>
                    <div className="prose prose-themed prose-sm max-w-none">
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
            <h2 className="text-lg font-semibold text-text-secondary mb-6" style={{ fontFamily: 'var(--font-serif)' }}>
              Final Decision
            </h2>
            <div className="surface-card bg-surface border border-accent/20 rounded-xl p-4 md:p-6">
              <div className="prose prose-themed max-w-none">
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
