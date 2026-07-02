import { useAnalysisStore } from '../../stores/analysisStore'
import { Clock, FileText, Cpu, TrendingUp } from 'lucide-react'

export default function StatsBar() {
  const stats = useAnalysisStore((s) => s.stats)
  const status = useAnalysisStore((s) => s.status)
  const agentStatus = useAnalysisStore((s) => s.agentStatus)

  const agentsCompleted = Object.values(agentStatus).filter((s) => s === 'completed').length
  const agentsTotal = Object.keys(agentStatus).length

  const elapsed = stats?.elapsed_seconds
    ? `${Math.floor(stats.elapsed_seconds / 60).toString().padStart(2, '0')}:${(stats.elapsed_seconds % 60).toString().padStart(2, '0')}`
    : '--:--'

  return (
    <div className="flex items-center gap-6 px-6 py-3 bg-gray-900/50 border-b border-gray-800 text-sm">
      <div className="flex items-center gap-2 text-gray-400">
        <TrendingUp className="w-4 h-4" />
        <span>
          Agents: {agentsCompleted}/{agentsTotal || '-'}
        </span>
      </div>

      <div className="flex items-center gap-2 text-gray-400">
        <FileText className="w-4 h-4" />
        <span>
          Reports: {stats?.reports_done || 0}/{stats?.reports_total || 7}
        </span>
      </div>

      <div className="flex items-center gap-2 text-gray-400">
        <Clock className="w-4 h-4" />
        <span>{elapsed}</span>
      </div>

      <div className="flex items-center gap-2 text-gray-400">
        <Cpu className="w-4 h-4" />
        <span
          className={
            status === 'running'
              ? 'text-blue-400'
              : status === 'completed'
              ? 'text-emerald-400'
              : status === 'failed'
              ? 'text-red-400'
              : 'text-gray-500'
          }
        >
          {status === 'running' ? 'Running...' : status === 'completed' ? 'Completed' : status === 'failed' ? 'Failed' : 'Idle'}
        </span>
      </div>
    </div>
  )
}
