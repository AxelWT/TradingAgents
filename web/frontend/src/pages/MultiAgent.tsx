import { Link } from 'react-router-dom'
import {
  LineChart,
  HeartPulse,
  Newspaper,
  Calculator,
  TrendingUp,
  TrendingDown,
  Scale,
  Wallet,
  Zap,
  Minus,
  Shield,
  Briefcase,
  ArrowRight,
  Play,
  ChevronRight,
} from 'lucide-react'

interface AgentInfo {
  name: string
  icon: React.ElementType
  description: string
}

interface TeamInfo {
  name: string
  stage: string
  color: string
  iconBg: string
  iconColor: string
  border: string
  agents: AgentInfo[]
}

const TEAMS: TeamInfo[] = [
  {
    name: 'Analyst Team',
    stage: 'Stage 1 · Data Gathering',
    color: 'blue',
    iconBg: 'bg-blue-500/10',
    iconColor: 'text-blue-400',
    border: 'border-blue-500/20',
    agents: [
      {
        name: 'Market Analyst',
        icon: LineChart,
        description: 'Analyzes price action, technical indicators, and market structure.',
      },
      {
        name: 'Sentiment Analyst',
        icon: HeartPulse,
        description: 'Gauges market sentiment from social media and community signals.',
      },
      {
        name: 'News Analyst',
        icon: Newspaper,
        description: 'Evaluates the market impact of news events and headlines.',
      },
      {
        name: 'Fundamentals Analyst',
        icon: Calculator,
        description: 'Reviews financial statements, earnings, and valuation metrics.',
      },
    ],
  },
  {
    name: 'Research Team',
    stage: 'Stage 2 · Debate',
    color: 'purple',
    iconBg: 'bg-purple-500/10',
    iconColor: 'text-purple-400',
    border: 'border-purple-500/20',
    agents: [
      {
        name: 'Bull Researcher',
        icon: TrendingUp,
        description: 'Builds the bullish case, arguing for upside potential.',
      },
      {
        name: 'Bear Researcher',
        icon: TrendingDown,
        description: 'Builds the bearish case, highlighting downside risks.',
      },
      {
        name: 'Research Manager',
        icon: Scale,
        description: 'Moderates the debate and synthesizes a balanced research verdict.',
      },
    ],
  },
  {
    name: 'Trading Team',
    stage: 'Stage 3 · Execution Plan',
    color: 'accent',
    iconBg: 'bg-accent/10',
    iconColor: 'text-accent',
    border: 'border-accent/20',
    agents: [
      {
        name: 'Trader',
        icon: Wallet,
        description: 'Translates the research verdict into a concrete trading plan.',
      },
    ],
  },
  {
    name: 'Risk Management',
    stage: 'Stage 4 · Risk Assessment',
    color: 'amber',
    iconBg: 'bg-amber-500/10',
    iconColor: 'text-amber-400',
    border: 'border-amber-500/20',
    agents: [
      {
        name: 'Aggressive Analyst',
        icon: Zap,
        description: 'Evaluates the trade from a high-risk, high-reward perspective.',
      },
      {
        name: 'Neutral Analyst',
        icon: Minus,
        description: 'Evaluates the trade from a balanced, moderate-risk perspective.',
      },
      {
        name: 'Conservative Analyst',
        icon: Shield,
        description: 'Evaluates the trade from a capital-preservation perspective.',
      },
    ],
  },
  {
    name: 'Portfolio Management',
    stage: 'Stage 5 · Final Decision',
    color: 'up',
    iconBg: 'bg-up/10',
    iconColor: 'text-up',
    border: 'border-up/20',
    agents: [
      {
        name: 'Portfolio Manager',
        icon: Briefcase,
        description: 'Aggregates all inputs and delivers the final trading decision.',
      },
    ],
  },
]

const totalAgents = TEAMS.reduce((sum, team) => sum + team.agents.length, 0)

export default function MultiAgent() {
  return (
    <div className="p-4 md:p-8 relative z-1">
      {/* Header */}
      <div className="mb-8">
        <div className="section-tag mb-2">Architecture</div>
        <h1
          className="text-2xl md:text-3xl font-bold text-text-primary"
          style={{ fontFamily: 'var(--font-serif)' }}
        >
          Multi-Agent System
        </h1>
        <p className="text-text-secondary mt-1">
          {totalAgents} specialized agents across {TEAMS.length} teams, working in a structured
          pipeline from data gathering to final decision.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <div className="surface-card p-4 bg-surface border border-border-subtle rounded-xl text-center">
          <div className="text-2xl font-bold text-accent">{totalAgents}</div>
          <div className="text-xs text-text-faint mt-1">Total Agents</div>
        </div>
        <div className="surface-card p-4 bg-surface border border-border-subtle rounded-xl text-center">
          <div className="text-2xl font-bold text-accent-2">{TEAMS.length}</div>
          <div className="text-xs text-text-faint mt-1">Teams</div>
        </div>
        <div className="surface-card p-4 bg-surface border border-border-subtle rounded-xl text-center">
          <div className="text-2xl font-bold text-purple-400">5</div>
          <div className="text-xs text-text-faint mt-1">Pipeline Stages</div>
        </div>
        <div className="surface-card p-4 bg-surface border border-border-subtle rounded-xl text-center">
          <div className="text-2xl font-bold text-up">1</div>
          <div className="text-xs text-text-faint mt-1">Final Decision</div>
        </div>
      </div>

      {/* Pipeline */}
      <div className="space-y-4">
        {TEAMS.map((team, teamIdx) => (
          <div key={team.name}>
            <div
              className={`surface-card bg-surface border ${team.border} rounded-xl p-4 md:p-6`}
            >
              {/* Team header */}
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <span
                    className={`flex items-center justify-center w-7 h-7 rounded-full ${team.iconBg} ${team.iconColor} text-sm font-bold`}
                  >
                    {teamIdx + 1}
                  </span>
                  <div>
                    <h2 className="text-lg font-semibold text-text-primary">{team.name}</h2>
                    <p className="text-xs text-text-faint">{team.stage}</p>
                  </div>
                </div>
                <span className="text-xs text-text-faint">
                  {team.agents.length} agent{team.agents.length > 1 ? 's' : ''}
                </span>
              </div>

              {/* Agent cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {team.agents.map((agent) => {
                  const Icon = agent.icon
                  return (
                    <div
                      key={agent.name}
                      className="bg-surface-2/50 rounded-lg p-4 border border-border-subtle hover:border-border-default transition-colors"
                    >
                      <div className={`inline-flex p-2 rounded-lg ${team.iconBg} mb-3`}>
                        <Icon className={`w-5 h-5 ${team.iconColor}`} />
                      </div>
                      <h3 className="text-sm font-medium text-text-primary mb-1">{agent.name}</h3>
                      <p className="text-xs text-text-secondary leading-relaxed">
                        {agent.description}
                      </p>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Connector arrow between teams */}
            {teamIdx < TEAMS.length - 1 && (
              <div className="flex justify-center py-1">
                <ArrowRight className="w-5 h-5 text-text-faint rotate-90" />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* CTA */}
      <div className="mt-8 surface-card bg-surface border border-border-subtle rounded-xl p-6 text-center">
        <h2 className="text-lg font-semibold text-text-primary mb-2">
          Ready to see the agents in action?
        </h2>
        <p className="text-text-secondary text-sm mb-4">
          Start a new analysis and watch all {totalAgents} agents collaborate in real time.
        </p>
        <Link
          to="/analysis"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-accent text-bg font-medium text-sm hover:bg-accent/90 transition-colors"
        >
          <Play className="w-4 h-4" />
          Start Analysis
        </Link>
      </div>

      {/* Breadcrumb back */}
      <div className="mt-6">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm text-text-faint hover:text-text-primary transition-colors"
        >
          <ChevronRight className="w-4 h-4 rotate-180" />
          Back to Dashboard
        </Link>
      </div>
    </div>
  )
}
