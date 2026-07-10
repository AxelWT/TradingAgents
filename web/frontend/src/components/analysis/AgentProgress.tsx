import { AgentStatus } from '../../stores/analysisStore'
import { Loader2, Check, Clock, AlertCircle } from 'lucide-react'

interface AgentProgressProps {
  agentStatus: AgentStatus
  teams: Record<string, string[]>
}

const statusIcon: Record<string, React.ReactNode> = {
  pending: <Clock className="w-3.5 h-3.5 text-yellow-500" />,
  in_progress: <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />,
  completed: <Check className="w-3.5 h-3.5 text-emerald-400" />,
  error: <AlertCircle className="w-3.5 h-3.5 text-red-400" />,
}

const statusText: Record<string, string> = {
  pending: 'Pending',
  in_progress: 'Running',
  completed: 'Done',
  error: 'Error',
}

export default function AgentProgress({ agentStatus, teams }: AgentProgressProps) {
  return (
    <div className="flex flex-col overflow-auto p-4">
      <h3 className="text-sm font-semibold text-text-faint uppercase tracking-wider mb-4">
        Agent Progress
      </h3>

      {Object.entries(teams).map(([team, agents]) => {
        const activeAgents = agents.filter((a) => a in agentStatus)
        if (activeAgents.length === 0) return null

        return (
          <div key={team} className="mb-4">
            <div className="text-xs font-medium text-text-faint mb-2 uppercase tracking-wider">
              {team}
            </div>
            <div className="space-y-1">
              {activeAgents.map((agent) => {
                const status = agentStatus[agent] || 'pending'
                return (
                  <div
                    key={agent}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-md bg-surface-2/50"
                  >
                    {statusIcon[status]}
                    <span className="text-sm text-text-secondary flex-1">{agent}</span>
                    <span
                      className={`text-xs ${
                        status === 'in_progress'
                          ? 'text-blue-400'
                          : status === 'completed'
                          ? 'text-emerald-400'
                          : status === 'error'
                          ? 'text-red-400'
                          : 'text-text-faint'
                      }`}
                    >
                      {statusText[status]}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
