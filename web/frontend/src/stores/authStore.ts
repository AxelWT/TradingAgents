import { create } from 'zustand'

interface User {
  id: string
  email: string
  display_name: string | null
  is_admin: boolean
  is_active: boolean
  is_whitelisted: boolean
}

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  setAuth: (user: User, token: string) => void
  clearAuth: () => void
  initialize: () => void
}

function isTokenExpired(token: string): boolean {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    if (!payload.exp) return false
    return Date.now() >= payload.exp * 1000 - 30_000
  } catch {
    return true
  }
}

function loadInitialState(): Pick<AuthState, 'user' | 'token' | 'isAuthenticated'> {
  const token = localStorage.getItem('access_token')
  const userStr = localStorage.getItem('user')
  if (token && userStr) {
    if (isTokenExpired(token)) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user')
      return { user: null, token: null, isAuthenticated: false }
    }
    try {
      return { user: JSON.parse(userStr), token, isAuthenticated: true }
    } catch {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user')
    }
  }
  return { user: null, token: null, isAuthenticated: false }
}

export const useAuthStore = create<AuthState>((set) => ({
  ...loadInitialState(),

  setAuth: (user, token) => {
    localStorage.setItem('access_token', token)
    localStorage.setItem('user', JSON.stringify(user))
    set({ user, token, isAuthenticated: true })
  },

  clearAuth: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('user')
    set({ user: null, token: null, isAuthenticated: false })
  },

  initialize: () => {
    set(loadInitialState())
  },
}))
