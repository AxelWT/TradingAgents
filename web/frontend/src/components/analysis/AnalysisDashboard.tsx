import { useAnalysisStore, AgentStatus } from '../../stores/analysisStore'
import AgentProgress from './AgentProgress'
import MessageFeed from './MessageFeed'
import AnalysisPanel from './AnalysisPanel'
import StatsBar from './StatsBar'

const ALL_AGENTS_STRUCTURED: Record<string, string[]> = {
  'Analyst Team': ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst'],
  'Research Team': ['Bull Researcher', 'Bear Researcher', 'Research Manager'],
  'Trading Team': ['Trader'],
  'Risk Management': ['Aggressive Analyst', 'Neutral Analyst', 'Conservative Analyst'],
  'Portfolio Management': ['Portfolio Manager'],
}

export default function AnalysisDashboard() {
  const { agentStatus, status, signal, error } = useAnalysisStore()

  const activeAgents: AgentStatus = {}
  for (const teamAgents of Object.values(ALL_AGENTS_STRUCTURED)) {
    for (const agent of teamAgents) {
      if (agent in agentStatus) {
        activeAgents[agent] = agentStatus[agent]
      }
    }
  }

  const agentsCompleted = Object.values(agentStatus).filter((s) => s === 'completed').length
  const agentsTotal = Object.keys(agentStatus).length

  return (
    <div className="h-full flex flex-col">
      <StatsBar />

      {status === 'failed' && error && (
        <div className="mx-6 mt-4 p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          Error: {error}
        </div>
      )}

      {status === 'completed' && signal && (
        <div className="mx-6 mt-4 p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-center">
          <span className="text-gray-400 mr-2">Final Signal:</span>
          <span
            className={`text-xl font-bold ${
              signal === 'Buy'
                ? 'text-emerald-400'
                : signal === 'Sell'
                ? 'text-red-400'
                : 'text-yellow-400'
            }`}
          >
            {signal}
          </span>
          <span className="text-gray-500 ml-4">
            {agentsCompleted}/{agentsTotal} agents completed
          </span>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <div className="w-[360px] border-r border-gray-800 flex flex-col overflow-hidden">
          <AgentProgress
            agentStatus={activeAgents}
            teams={ALL_AGENTS_STRUCTURED}
          />
        </div>

        <div className="w-[400px] border-r border-gray-800 flex flex-col overflow-hidden">
          <MessageFeed />
        </div>

        <div className="flex-1 flex flex-col overflow-hidden">
          <AnalysisPanel />
        </div>
      </div>
    </div>
  )
}
