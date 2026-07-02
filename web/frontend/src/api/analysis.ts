import api from './client'

export interface AnalysisTask {
  id: string
  ticker: string
  asset_type: string
  trade_date: string
  status: string
  signal: string | null
  rating: string | null
  final_report: string | null
  agent_reports: Record<string, string> | null
  token_usage: Record<string, unknown> | null
  error_message: string | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

export interface AnalysisListResponse {
  tasks: AnalysisTask[]
  total: number
}

export interface CreateAnalysisParams {
  ticker: string
  trade_date: string
  asset_type?: string
  analysts?: string[]
  research_depth?: number
  llm_provider?: string
  backend_url?: string
  quick_think_llm?: string
  deep_think_llm?: string
  output_language?: string
  google_thinking_level?: string
  openai_reasoning_effort?: string
  anthropic_effort?: string
}

export const analysisApi = {
  create: async (params: CreateAnalysisParams): Promise<AnalysisTask> => {
    const { data } = await api.post('/api/analysis', params)
    return data
  },

  list: async (page = 1, pageSize = 20, status?: string): Promise<AnalysisListResponse> => {
    const params: Record<string, string | number> = { page, page_size: pageSize }
    if (status) params.status = status
    const { data } = await api.get('/api/analysis', { params })
    return data
  },

  get: async (taskId: string): Promise<AnalysisTask> => {
    const { data } = await api.get(`/api/analysis/${taskId}`)
    return data
  },
}
