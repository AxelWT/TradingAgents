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
