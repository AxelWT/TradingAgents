import { create } from 'zustand'

export interface AgentStatus {
  [agentName: string]: 'pending' | 'in_progress' | 'completed' | 'error'
}

export interface WSMessage {
  type: string
  [key: string]: unknown
}

interface AnalysisState {
  taskId: string | null
  status: string
  agentStatus: AgentStatus
  reportSections: Record<string, string>
  messages: Array<{ timestamp: string; type: string; content: string }>
  toolCalls: Array<{ timestamp: string; tool: string; args: unknown }>
  stats: {
    elapsed_seconds: number
    reports_done: number
    reports_total: number
  } | null
  signal: string | null
  finalReport: string | null
  error: string | null

  startAnalysis: (taskId: string) => void
  reset: () => void
  processWSMessage: (msg: WSMessage) => void
}

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  taskId: null,
  status: 'idle',
  agentStatus: {},
  reportSections: {},
  messages: [],
  toolCalls: [],
  stats: null,
  signal: null,
  finalReport: null,
  error: null,

  startAnalysis: (taskId) => {
    set({
      taskId,
      status: 'running',
      agentStatus: {},
      reportSections: {},
      messages: [],
      toolCalls: [],
      stats: null,
      signal: null,
      finalReport: null,
      error: null,
    })
  },

  reset: () => {
    set({
      taskId: null,
      status: 'idle',
      agentStatus: {},
      reportSections: {},
      messages: [],
      toolCalls: [],
      stats: null,
      signal: null,
      finalReport: null,
      error: null,
    })
  },

  processWSMessage: (msg) => {
    const timestamp = new Date().toLocaleTimeString()
    switch (msg.type) {
      case 'agent_status':
        set((s) => ({
          agentStatus: {
            ...s.agentStatus,
            [msg.agent as string]: msg.status as AgentStatus[string],
          },
        }))
        break
      case 'tool_call':
        set((s) => ({
          toolCalls: [
            ...s.toolCalls,
            { timestamp, tool: msg.tool as string, args: msg.args },
          ],
        }))
        break
      case 'report':
        set((s) => ({
          reportSections: {
            ...s.reportSections,
            [msg.section as string]: msg.content as string,
          },
        }))
        break
      case 'message':
        set((s) => ({
          messages: [
            ...s.messages,
            { timestamp, type: msg.msg_type as string, content: msg.content as string },
          ],
        }))
        break
      case 'stats':
        set({
          stats: {
            elapsed_seconds: msg.elapsed_seconds as number,
            reports_done: msg.reports_done as number,
            reports_total: msg.reports_total as number,
          },
        })
        break
      case 'complete':
        set({
          status: 'completed',
          signal: msg.signal as string,
          finalReport: msg.final_report as string,
        })
        break
      case 'error':
        set({ status: 'failed', error: msg.message as string })
        break
    }
  },
}))
