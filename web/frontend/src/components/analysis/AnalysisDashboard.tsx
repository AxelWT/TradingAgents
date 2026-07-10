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
        <div className="mx-4 md:mx-6 mt-4 p-4 bg-down/10 border border-down/20 rounded-lg text-down text-sm">
          Error: {error}
        </div>
      )}

      {status === 'completed' && signal && (
        <div className="surface-card mx-4 md:mx-6 mt-4 p-4 bg-accent/5 border border-accent/20 rounded-lg text-center">
          <span className="text-text-secondary mr-2">Final Signal:</span>
          <span
            className={`text-xl font-bold ${
              signal === 'Buy'
                ? 'text-up'
                : signal === 'Sell'
                ? 'text-down'
                : 'text-yellow-400'
            }`}
          >
            {signal}
          </span>
          <span className="text-text-faint ml-4">
            {agentsCompleted}/{agentsTotal} agents completed
          </span>
        </div>
      )}

      <div className="flex-1 flex flex-col md:flex-row overflow-y-auto md:overflow-hidden">
        <div className="border-b md:border-b-0 md:border-r border-border-subtle flex flex-col md:overflow-hidden md:w-[360px] shrink-0">
          <AgentProgress
            agentStatus={activeAgents}
            teams={ALL_AGENTS_STRUCTURED}
          />
        </div>

        <div className="border-b md:border-b-0 md:border-r border-border-subtle flex flex-col md:overflow-hidden md:w-[400px] shrink-0">
          <MessageFeed />
        </div>

        <div className="flex-1 flex flex-col md:overflow-hidden">
          <AnalysisPanel />
        </div>
      </div>
    </div>
  )
}
