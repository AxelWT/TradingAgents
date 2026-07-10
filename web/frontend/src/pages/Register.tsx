import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuth } from '../hooks/useAuth'
import { TrendingUp, Mail, Lock, AlertCircle, CheckCircle, KeyRound } from 'lucide-react'
import ThemeToggle from '../components/ui/ThemeToggle'

export default function Register() {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [success, setSuccess] = useState(false)
  const [loading, setLoading] = useState(false)
  const [sendingCode, setSendingCode] = useState(false)
  const [countdown, setCountdown] = useState(0)
  const { setAuth } = useAuth()
  const navigate = useNavigate()
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [])

  const startCountdown = (seconds: number) => {
    setCountdown(seconds)
    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current)
          return 0
        }
        return prev - 1
      })
    }, 1000)
  }

  const handleSendCode = async () => {
    setError('')
    setInfo('')

    if (!email) {
      setError('Please enter your email first')
      return
    }

    setSendingCode(true)
    try {
      const resp = await authApi.sendCode({ email })
      setInfo(resp.message)
      startCountdown(resp.expire_seconds > 60 ? 60 : resp.expire_seconds)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to send verification code'
      setError(msg)
    } finally {
      setSendingCode(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setInfo('')

    if (!code) {
      setError('Please enter the verification code')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters')
      return
    }

    setLoading(true)

    try {
      const resp = await authApi.register({ email, password, code })
      setAuth(resp.user, resp.access_token)
      setSuccess(true)
      setTimeout(() => navigate('/'), 1500)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Registration failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="relative min-h-screen bg-bg flex items-center justify-center p-4 overflow-hidden">
        <div className="bg-grid" />
        <div className="bg-glow" />
        <div className="bg-glow" />
        <div className="bg-glow" />
        <div className="relative z-1 text-center">
          <CheckCircle className="w-16 h-16 text-accent mx-auto mb-4" />
          <h2 className="text-2xl font-bold text-text-primary" style={{ fontFamily: 'var(--font-serif)' }}>
            Registration Successful!
          </h2>
          <p className="text-text-secondary">Redirecting to dashboard...</p>
        </div>
      </div>
    )
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
          <p className="text-text-secondary mt-2">Create your account</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="surface-card bg-surface rounded-2xl p-8 border border-border-subtle"
        >
          {error && (
            <div className="flex items-center gap-2 p-3 mb-6 bg-down/10 border border-down/20 rounded-lg text-down text-sm">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}
          {info && !error && (
            <div className="flex items-center gap-2 p-3 mb-6 bg-accent/10 border border-accent/20 rounded-lg text-accent text-sm">
              <CheckCircle className="w-4 h-4 shrink-0" />
              {info}
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
                  className="w-full pl-11 pr-28 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
                  placeholder="you@example.com"
                  required
                />
                <button
                  type="button"
                  onClick={handleSendCode}
                  disabled={sendingCode || countdown > 0}
                  className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1.5 text-xs font-medium rounded-md bg-gradient-to-r from-accent to-accent-2 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed text-bg transition-opacity whitespace-nowrap"
                >
                  {sendingCode ? 'Sending...' : countdown > 0 ? `Resend in ${countdown}s` : 'Send Code'}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-2">Verification Code</label>
              <div className="relative">
                <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-faint" />
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                  className="w-full pl-11 pr-4 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors tracking-widest"
                  placeholder="Enter 6-digit code"
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
                  placeholder="At least 6 characters"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-text-secondary mb-2">Confirm Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-faint" />
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full pl-11 pr-4 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
                  placeholder="Re-enter password"
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-gradient-to-r from-accent to-accent-2 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed text-bg font-medium rounded-lg transition-opacity"
            >
              {loading ? 'Registering...' : 'Register'}
            </button>
          </div>

          <p className="mt-6 text-center text-sm text-text-secondary">
            Already have an account?{' '}
            <Link to="/login" className="text-accent hover:opacity-80">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
