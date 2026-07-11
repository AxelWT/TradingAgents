import api from './client'

export interface AdminUser {
  id: string
  email: string
  display_name: string | null
  is_admin: boolean
  is_active: boolean
  is_whitelisted: boolean
  created_at: string | null
  task_count: number
}

export interface AdminUserListResponse {
  users: AdminUser[]
  total: number
}

export interface AdminStats {
  total_users: number
  active_users: number
  blacklisted_users: number
  whitelisted_users: number
  admin_users: number
  total_tasks: number
  access_mode: string
}

export interface AdminUserUpdateParams {
  is_active?: boolean
  is_whitelisted?: boolean
  is_admin?: boolean
}

export const adminApi = {
  getStats: async (): Promise<AdminStats> => {
    const { data } = await api.get('/api/admin/stats')
    return data
  },

  listUsers: async (params: {
    page?: number
    page_size?: number
    search?: string
    status_filter?: string
  }): Promise<AdminUserListResponse> => {
    const { data } = await api.get('/api/admin/users', { params })
    return data
  },

  getUser: async (userId: string): Promise<AdminUser> => {
    const { data } = await api.get(`/api/admin/users/${userId}`)
    return data
  },

  deleteUser: async (userId: string): Promise<void> => {
    await api.delete(`/api/admin/users/${userId}`)
  },

  updateUser: async (userId: string, params: AdminUserUpdateParams): Promise<AdminUser> => {
    const { data } = await api.patch(`/api/admin/users/${userId}`, params)
    return data
  },

  addToBlacklist: async (userId: string): Promise<AdminUser> => {
    const { data } = await api.post(`/api/admin/users/${userId}/blacklist`)
    return data
  },

  removeFromBlacklist: async (userId: string): Promise<AdminUser> => {
    const { data } = await api.delete(`/api/admin/users/${userId}/blacklist`)
    return data
  },

  addToWhitelist: async (userId: string): Promise<AdminUser> => {
    const { data } = await api.post(`/api/admin/users/${userId}/whitelist`)
    return data
  },

  removeFromWhitelist: async (userId: string): Promise<AdminUser> => {
    const { data } = await api.delete(`/api/admin/users/${userId}/whitelist`)
    return data
  },

  getAccessMode: async (): Promise<{ access_mode: string }> => {
    const { data } = await api.get('/api/admin/access-mode')
    return data
  },

  updateAccessMode: async (accessMode: string): Promise<{ access_mode: string }> => {
    const { data } = await api.put('/api/admin/access-mode', { access_mode: accessMode })
    return data
  },
}

export interface ScheduledJob {
  id: string
  name: string
  ticker: string
  asset_type: string
  analysts: string[] | null
  research_depth: number
  llm_provider: string
  backend_url: string | null
  quick_think_llm: string | null
  deep_think_llm: string | null
  output_language: string
  google_thinking_level: string | null
  openai_reasoning_effort: string | null
  anthropic_effort: string | null
  cron_expr: string
  enabled: boolean
  created_by: string
  created_at: string | null
  next_run_at: string | null
  last_run_at: string | null
  last_task_id: string | null
  last_error: string | null
}

export interface ScheduledJobListResponse {
  jobs: ScheduledJob[]
  total: number
}

export interface ScheduledJobCreateParams {
  name: string
  ticker: string
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
  cron_expr: string
  enabled?: boolean
}

export type ScheduledJobUpdateParams = Partial<ScheduledJobCreateParams>

export interface ScheduledJobRunResponse {
  task_id: string
  message: string
}

export const scheduledJobsApi = {
  list: async (page = 1, pageSize = 20): Promise<ScheduledJobListResponse> => {
    const { data } = await api.get('/api/admin/scheduled-jobs', { params: { page, page_size: pageSize } })
    return data
  },

  get: async (jobId: string): Promise<ScheduledJob> => {
    const { data } = await api.get(`/api/admin/scheduled-jobs/${jobId}`)
    return data
  },

  create: async (params: ScheduledJobCreateParams): Promise<ScheduledJob> => {
    const { data } = await api.post('/api/admin/scheduled-jobs', params)
    return data
  },

  update: async (jobId: string, params: ScheduledJobUpdateParams): Promise<ScheduledJob> => {
    const { data } = await api.patch(`/api/admin/scheduled-jobs/${jobId}`, params)
    return data
  },

  delete: async (jobId: string): Promise<void> => {
    await api.delete(`/api/admin/scheduled-jobs/${jobId}`)
  },

  run: async (jobId: string): Promise<ScheduledJobRunResponse> => {
    const { data } = await api.post(`/api/admin/scheduled-jobs/${jobId}/run`)
    return data
  },
}
