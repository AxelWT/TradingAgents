import api from './client'

export interface AuthResponse {
  access_token: string
  token_type: string
  user: {
    id: string
    email: string
    display_name: string | null
  }
}

export interface LoginParams {
  email: string
  password: string
}

export interface RegisterParams {
  email: string
  password: string
}

export const authApi = {
  login: async (params: LoginParams): Promise<AuthResponse> => {
    const { data } = await api.post('/api/auth/login', params)
    return data
  },

  register: async (params: RegisterParams): Promise<AuthResponse> => {
    const { data } = await api.post('/api/auth/register', params)
    return data
  },

  getMe: async () => {
    const { data } = await api.get('/api/auth/me')
    return data
  },

  logout: async () => {
    await api.post('/api/auth/logout')
  },
}
