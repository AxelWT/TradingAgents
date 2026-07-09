import { useAuthStore } from '../stores/authStore'

export function useAuth() {
  const { user, isAuthenticated, setAuth, clearAuth } = useAuthStore()

  return { user, isAuthenticated, setAuth, clearAuth }
}
