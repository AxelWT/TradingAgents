import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminApi, AdminStats } from '../../api/admin'
import { Users, Ban, CheckCircle, Shield, BarChart3, Lock, Unlock } from 'lucide-react'

export default function AdminDashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    loadStats()
  }, [])

  const loadStats = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await adminApi.getStats()
      setStats(data)
    } catch {
      setError('Failed to load stats')
    } finally {
      setLoading(false)
    }
  }

  const handleToggleAccessMode = async () => {
    if (!stats) return
    const newMode = stats.access_mode === 'open' ? 'whitelist' : 'open'
    if (
      !window.confirm(
        newMode === 'whitelist'
          ? 'Switching to whitelist mode: only whitelisted users will be able to log in. Continue?'
          : 'Switching to open mode: all non-blacklisted users will be able to log in. Continue?'
      )
    )
      return
    setSwitching(true)
    try {
      await adminApi.updateAccessMode(newMode)
      setStats({ ...stats, access_mode: newMode })
    } catch {
      window.alert('Failed to switch access mode')
    } finally {
      setSwitching(false)
    }
  }

  const statCards = stats
    ? [
        {
          label: 'Total Users',
          value: stats.total_users,
          icon: Users,
          color: 'text-blue-400 bg-blue-400/10',
        },
        {
          label: 'Active Users',
          value: stats.active_users,
          icon: CheckCircle,
          color: 'text-up bg-up/10',
        },
        {
          label: 'Blacklisted',
          value: stats.blacklisted_users,
          icon: Ban,
          color: 'text-down bg-down/10',
        },
        {
          label: 'Whitelisted',
          value: stats.whitelisted_users,
          icon: Shield,
          color: 'text-purple-400 bg-purple-400/10',
        },
        {
          label: 'Admins',
          value: stats.admin_users,
          icon: Lock,
          color: 'text-yellow-400 bg-yellow-400/10',
        },
        {
          label: 'Total Tasks',
          value: stats.total_tasks,
          icon: BarChart3,
          color: 'text-cyan-400 bg-cyan-400/10',
        },
      ]
    : []

  return (
    <div className="p-4 md:p-8 relative z-1">
      <div className="mb-8">
        <div className="section-tag mb-2">Administration</div>
        <h1 className="text-2xl md:text-3xl font-bold text-text-primary" style={{ fontFamily: 'var(--font-serif)' }}>
          Admin Panel
        </h1>
        <p className="text-text-secondary mt-1">System overview & access control</p>
      </div>

      {loading ? (
        <div className="text-text-secondary text-center py-12">Loading...</div>
      ) : error ? (
        <div className="text-down text-center py-12">{error}</div>
      ) : stats ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 md:gap-6 mb-8">
            {statCards.map(({ label, value, icon: Icon, color }) => (
              <div
                key={label}
                className="surface-card flex items-center gap-4 p-4 md:p-6 bg-surface border border-border-subtle rounded-xl"
              >
                <div className={`p-3 rounded-lg ${color}`}>
                  <Icon className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-text-primary" style={{ fontFamily: 'var(--font-mono)' }}>
                    {value}
                  </p>
                  <p className="text-text-faint text-sm">{label}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="surface-card p-4 md:p-6 bg-surface border border-border-subtle rounded-xl mb-8">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                {stats.access_mode === 'whitelist' ? (
                  <Lock className="w-5 h-5 text-yellow-400" />
                ) : (
                  <Unlock className="w-5 h-5 text-up" />
                )}
                <div>
                  <h3 className="text-text-primary font-medium">Access Mode</h3>
                  <p className="text-text-faint text-sm">
                    {stats.access_mode === 'whitelist'
                      ? 'Whitelist mode: only whitelisted users can log in'
                      : 'Open mode: all non-blacklisted users can log in'}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className={`px-3 py-1 rounded-full text-xs font-medium ${
                    stats.access_mode === 'whitelist'
                      ? 'text-yellow-400 bg-yellow-400/10'
                      : 'text-up bg-up/10'
                  }`}
                >
                  {stats.access_mode === 'whitelist' ? 'Whitelist' : 'Open'}
                </span>
                <button
                  onClick={handleToggleAccessMode}
                  disabled={switching}
                  className="px-4 py-2 bg-surface-2 border border-border-subtle rounded-lg text-sm text-text-secondary hover:border-border-strong transition-colors disabled:opacity-50"
                >
                  Switch to {stats.access_mode === 'open' ? 'Whitelist' : 'Open'}
                </button>
              </div>
            </div>
          </div>

          <Link
            to="/admin/users"
            className="surface-card flex items-center gap-4 p-4 md:p-6 bg-surface border border-border-subtle rounded-xl hover:border-accent/50 hover:-translate-y-0.5 transition-all duration-300 group"
          >
            <div className="p-3 bg-accent/10 rounded-lg">
              <Users className="w-6 h-6 text-accent" />
            </div>
            <div>
              <h3 className="text-text-primary font-medium group-hover:text-accent transition-colors">
                User Management
              </h3>
              <p className="text-text-faint text-sm">View all registered users, manage blacklist/whitelist, delete users</p>
            </div>
          </Link>
        </>
      ) : null}
    </div>
  )
}
