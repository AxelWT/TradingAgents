import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { analysisApi, AnalysisTask } from '../api/analysis'
import { Play, FileText, TrendingUp, Clock, AlertCircle, Trash2 } from 'lucide-react'

export default function Dashboard() {
  const [recentTasks, setRecentTasks] = useState<AnalysisTask[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    loadRecentTasks()
  }, [])

  const loadRecentTasks = async () => {
    try {
      const resp = await analysisApi.list(1, 5)
      setRecentTasks(resp.tasks)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (taskId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!window.confirm('Delete this analysis? This action cannot be undone.')) return
    try {
      await analysisApi.delete(taskId)
      await loadRecentTasks()
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        window.alert('This analysis is still running and cannot be deleted')
      } else {
        window.alert('Failed to delete, please try again later')
      }
    }
  }

  const statusColor: Record<string, string> = {
    pending: 'text-yellow-400 bg-yellow-400/10',
    running: 'text-blue-400 bg-blue-400/10',
    completed: 'text-emerald-400 bg-emerald-400/10',
    failed: 'text-red-400 bg-red-400/10',
  }

  const signalColor: Record<string, string> = {
    Buy: 'text-emerald-400',
    Hold: 'text-yellow-400',
    Sell: 'text-red-400',
  }

  return (
    <div className="p-4 md:p-8 relative z-1">
      <div className="mb-8">
        <div className="section-tag mb-2">Overview</div>
        <h1 className="text-2xl md:text-3xl font-bold text-text-primary" style={{ fontFamily: 'var(--font-serif)' }}>
          Dashboard
        </h1>
        <p className="text-text-secondary mt-1">Welcome to TradingAgents</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6 mb-8">
        <button
          onClick={() => navigate('/analysis')}
          className="surface-card flex items-center gap-3 md:gap-4 p-4 md:p-6 bg-surface border border-border-subtle rounded-xl hover:border-accent/50 hover:-translate-y-1 transition-all duration-300 group text-left"
        >
          <div className="p-3 bg-accent/10 rounded-lg">
            <Play className="w-6 h-6 text-accent" />
          </div>
          <div>
            <h3 className="text-text-primary font-medium group-hover:text-accent transition-colors">
              New Analysis
            </h3>
            <p className="text-text-faint text-sm">Start a trading analysis</p>
          </div>
        </button>

        <Link
          to="/reports"
          className="surface-card flex items-center gap-3 md:gap-4 p-4 md:p-6 bg-surface border border-border-subtle rounded-xl hover:border-accent-2/50 hover:-translate-y-1 transition-all duration-300 group"
        >
          <div className="p-3 bg-accent-2/10 rounded-lg">
            <FileText className="w-6 h-6 text-accent-2" />
          </div>
          <div>
            <h3 className="text-text-primary font-medium group-hover:text-accent-2 transition-colors">
              Reports
            </h3>
            <p className="text-text-faint text-sm">View past analyses</p>
          </div>
        </Link>

        <div className="surface-card flex items-center gap-3 md:gap-4 p-4 md:p-6 bg-surface border border-border-subtle rounded-xl">
          <div className="p-3 bg-purple-500/10 rounded-lg">
            <TrendingUp className="w-6 h-6 text-purple-400" />
          </div>
          <div>
            <h3 className="text-text-primary font-medium">Multi-Agent</h3>
            <p className="text-text-faint text-sm">8 specialized agents</p>
          </div>
        </div>
      </div>

      <div>
        <h2 className="text-xl font-semibold text-text-primary mb-4">Recent Analyses</h2>
        {loading ? (
          <div className="text-text-secondary text-center py-12">Loading...</div>
        ) : recentTasks.length === 0 ? (
          <div className="text-text-secondary text-center py-12 bg-surface rounded-xl border border-border-subtle">
            <Clock className="w-8 h-8 mx-auto mb-3 text-text-faint" />
            <p>No analyses yet. Start your first one!</p>
          </div>
        ) : (
          <div className="space-y-3">
            {recentTasks.map((task) => (
              <div
                key={task.id}
                className="flex flex-wrap items-center justify-between gap-3 p-4 bg-surface border border-border-subtle rounded-lg hover:border-border-strong transition-colors cursor-pointer"
                onClick={() => {
                  if (task.status === 'completed') {
                    navigate(`/reports/${task.id}`)
                  } else {
                    navigate(`/analysis/${task.id}`)
                  }
                }}
              >
                <div className="flex items-center gap-4">
                  <div>
                    <span className="text-text-primary font-medium">{task.ticker}</span>
                    <span className="text-text-faint text-sm ml-3">{task.trade_date}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3 md:gap-4">
                  {task.signal && (
                    <span className={`font-semibold ${signalColor[task.signal] || 'text-text-secondary'}`}>
                      {task.signal}
                    </span>
                  )}
                  <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${statusColor[task.status] || ''}`}>
                    {task.status}
                  </span>
                  {task.error_message && (
                    <AlertCircle className="w-4 h-4 text-red-400" />
                  )}
                  <button
                    onClick={(e) => handleDelete(task.id, e)}
                    disabled={task.status === 'pending' || task.status === 'running'}
                    className="p-1.5 text-text-faint hover:text-red-400 transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-text-faint"
                    title={
                      task.status === 'pending' || task.status === 'running'
                      ? 'Cannot delete while running'
                        : 'Delete analysis'
                    }
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
