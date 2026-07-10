import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuth } from '../hooks/useAuth'
import { TrendingUp, Mail, Lock, AlertCircle } from 'lucide-react'
import ThemeToggle from '../components/ui/ThemeToggle'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { setAuth } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const resp = await authApi.login({ email, password })
      setAuth(resp.user, resp.access_token)
      navigate('/')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Login failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative min-h-screen bg-bg flex items-center justify-center p-4 overflow-hidden">
      <div className="bg-grid" />
      <div className="bg-glow" />
      <div className="bg-glow" />
      <div className="bg-glow" />
      <div className="absolute top-6 right-6 z-10">
        <ThemeToggle />
      </div>

      <div className="relative z-1 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center mx-auto mb-4">
            <TrendingUp className="w-7 h-7 text-bg" />
          </div>
          <h1 className="text-3xl font-bold text-text-primary" style={{ fontFamily: 'var(--font-serif)' }}>
            TradingAgents
          </h1>
          <p className="text-text-secondary mt-2">Sign in to your account</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="surface-card bg-surface rounded-2xl p-8 border border-border-subtle"
        >
          {error && (
            <div className="flex items-center gap-2 p-3 mb-6 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-2">Email</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-faint" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-11 pr-4 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
                  placeholder="you@example.com"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-2">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-faint" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full pl-11 pr-4 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
                  placeholder="Enter password"
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-gradient-to-r from-accent to-accent-2 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed text-bg font-medium rounded-lg transition-opacity flex items-center justify-center gap-2"
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </div>

          <p className="mt-6 text-center text-sm text-text-secondary">
            Don't have an account?{' '}
            <Link to="/register" className="text-accent hover:opacity-80">
              Sign up
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
