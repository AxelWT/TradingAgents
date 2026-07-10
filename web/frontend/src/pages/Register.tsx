import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuth } from '../hooks/useAuth'
import { TrendingUp, Mail, Lock, AlertCircle, CheckCircle, KeyRound } from 'lucide-react'

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
      setError('请先输入邮箱')
      return
    }

    setSendingCode(true)
    try {
      const resp = await authApi.sendCode({ email })
      setInfo(resp.message)
      startCountdown(resp.expire_seconds > 60 ? 60 : resp.expire_seconds)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '验证码发送失败'
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
      setError('请输入验证码')
      return
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }
    if (password.length < 6) {
      setError('密码至少需要 6 个字符')
      return
    }

    setLoading(true)

    try {
      const resp = await authApi.register({ email, password, code })
      setAuth(resp.user, resp.access_token)
      setSuccess(true)
      setTimeout(() => navigate('/'), 1500)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '注册失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
        <div className="text-center">
          <CheckCircle className="w-16 h-16 text-emerald-500 mx-auto mb-4" />
          <h2 className="text-2xl font-bold text-white mb-2">注册成功！</h2>
          <p className="text-gray-400">正在跳转到控制台...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <TrendingUp className="w-12 h-12 text-emerald-500 mx-auto mb-4" />
          <h1 className="text-3xl font-bold text-white">TradingAgents</h1>
          <p className="text-gray-500 mt-2">创建你的账号</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-gray-900 rounded-xl p-8 border border-gray-800">
          {error && (
            <div className="flex items-center gap-2 p-3 mb-6 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}
          {info && !error && (
            <div className="flex items-center gap-2 p-3 mb-6 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-400 text-sm">
              <CheckCircle className="w-4 h-4 shrink-0" />
              {info}
            </div>
          )}

          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">邮箱</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-11 pr-28 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                  placeholder="you@example.com"
                  required
                />
                <button
                  type="button"
                  onClick={handleSendCode}
                  disabled={sendingCode || countdown > 0}
                  className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors whitespace-nowrap"
                >
                  {sendingCode ? '发送中...' : countdown > 0 ? `${countdown}s 后重发` : '发送验证码'}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">验证码</label>
              <div className="relative">
                <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                  className="w-full pl-11 pr-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 tracking-widest"
                  placeholder="请输入 6 位验证码"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">密码</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full pl-11 pr-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                  placeholder="至少 6 个字符"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">确认密码</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full pl-11 pr-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                  placeholder="再次输入密码"
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium rounded-lg transition-colors"
            >
              {loading ? '注册中...' : '注册'}
            </button>
          </div>

          <p className="mt-6 text-center text-sm text-gray-500">
            已有账号？{' '}
            <Link to="/login" className="text-emerald-400 hover:text-emerald-300">
              登录
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
