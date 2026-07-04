import api from './client'
import { AnalysisTask, AnalysisListResponse } from './analysis'

export const reportsApi = {
  list: async (page = 1, pageSize = 20, ticker?: string): Promise<AnalysisListResponse> => {
    const params: Record<string, string | number> = { page, page_size: pageSize }
    if (ticker) params.ticker = ticker
    const { data } = await api.get('/api/reports', { params })
    return data
  },

  get: async (taskId: string): Promise<AnalysisTask> => {
    const { data } = await api.get(`/api/reports/${taskId}`)
    return data
  },

  download: async (taskId: string): Promise<string> => {
    const { data } = await api.get(`/api/reports/${taskId}/download`, {
      responseType: 'text',
    })
    return data
  },

  delete: async (taskId: string): Promise<void> => {
    await api.delete(`/api/analysis/${taskId}`)
  },
}
