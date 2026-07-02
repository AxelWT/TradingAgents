import { useEffect } from 'react'
import { useAuthStore } from '../stores/authStore'

export function useAuth() {
  const { user, isAuthenticated, setAuth, clearAuth, initialize } = useAuthStore()

  useEffect(() => {
    initialize()
  }, [initialize])

  return { user, isAuthenticated, setAuth, clearAuth }
}
