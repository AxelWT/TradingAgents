import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { analysisApi, AnalysisTask } from '../api/analysis'
import { Play, FileText, TrendingUp, Clock, AlertCircle } from 'lucide-react'

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
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Dashboard</h1>
        <p className="text-gray-500 mt-1">Welcome to TradingAgents</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <button
          onClick={() => navigate('/analysis')}
          className="flex items-center gap-4 p-6 bg-gray-900 border border-gray-800 rounded-xl hover:border-emerald-500/50 transition-colors group"
        >
          <div className="p-3 bg-emerald-500/10 rounded-lg">
            <Play className="w-6 h-6 text-emerald-400" />
          </div>
          <div className="text-left">
            <h3 className="text-white font-medium group-hover:text-emerald-400 transition-colors">
              New Analysis
            </h3>
            <p className="text-gray-500 text-sm">Start a trading analysis</p>
          </div>
        </button>

        <Link
          to="/reports"
          className="flex items-center gap-4 p-6 bg-gray-900 border border-gray-800 rounded-xl hover:border-blue-500/50 transition-colors group"
        >
          <div className="p-3 bg-blue-500/10 rounded-lg">
            <FileText className="w-6 h-6 text-blue-400" />
          </div>
          <div>
            <h3 className="text-white font-medium group-hover:text-blue-400 transition-colors">
              Reports
            </h3>
            <p className="text-gray-500 text-sm">View past analyses</p>
          </div>
        </Link>

        <div className="flex items-center gap-4 p-6 bg-gray-900 border border-gray-800 rounded-xl">
          <div className="p-3 bg-purple-500/10 rounded-lg">
            <TrendingUp className="w-6 h-6 text-purple-400" />
          </div>
          <div>
            <h3 className="text-white font-medium">Multi-Agent</h3>
            <p className="text-gray-500 text-sm">8 specialized agents</p>
          </div>
        </div>
      </div>

      <div>
        <h2 className="text-xl font-semibold text-white mb-4">Recent Analyses</h2>
        {loading ? (
          <div className="text-gray-500 text-center py-12">Loading...</div>
        ) : recentTasks.length === 0 ? (
          <div className="text-gray-500 text-center py-12 bg-gray-900 rounded-xl border border-gray-800">
            <Clock className="w-8 h-8 mx-auto mb-3 text-gray-600" />
            <p>No analyses yet. Start your first one!</p>
          </div>
        ) : (
          <div className="space-y-3">
            {recentTasks.map((task) => (
              <div
                key={task.id}
                className="flex items-center justify-between p-4 bg-gray-900 border border-gray-800 rounded-lg hover:border-gray-700 transition-colors cursor-pointer"
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
                    <span className="text-white font-medium">{task.ticker}</span>
                    <span className="text-gray-500 text-sm ml-3">{task.trade_date}</span>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  {task.signal && (
                    <span className={`font-semibold ${signalColor[task.signal] || 'text-gray-400'}`}>
                      {task.signal}
                    </span>
                  )}
                  <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${statusColor[task.status] || ''}`}>
                    {task.status}
                  </span>
                  {task.error_message && (
                    <AlertCircle className="w-4 h-4 text-red-400" />
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
