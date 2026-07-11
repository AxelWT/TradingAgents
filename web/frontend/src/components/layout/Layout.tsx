import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { authApi } from '../../api/auth'
import { BarChart3, Play, FileText, LogOut, TrendingUp, Menu, X, Shield, Clock } from 'lucide-react'
import ThemeToggle from '../ui/ThemeToggle'

export default function Layout() {
  const { user, clearAuth } = useAuth()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } catch {
      // ignore
    }
    clearAuth()
    navigate('/login')
  }

  const navItems = [
    { to: '/', icon: BarChart3, label: 'Dashboard' },
    { to: '/analysis', icon: Play, label: 'New Analysis' },
    { to: '/reports', icon: FileText, label: 'Reports' },
    ...(user?.is_admin
      ? [
          { to: '/admin/scheduled-jobs', icon: Clock, label: 'Scheduled' },
          { to: '/admin', icon: Shield, label: 'Admin' },
        ]
      : []),
  ]

  return (
    <div className="relative flex h-screen bg-bg text-text-primary">
      <div className="bg-grid" />
      <div className="bg-glow" />
      <div className="bg-glow" />
      <div className="bg-glow" />

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 bg-surface border-r border-border-subtle flex flex-col transform transition-transform duration-200 md:static md:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-6 border-b border-border-subtle flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center">
              <TrendingUp className="w-5 h-5 text-bg" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-text-primary" style={{ fontFamily: 'var(--font-serif)' }}>
                TradingAgents
              </h1>
              <p className="text-xs text-text-faint">Multi-Agent Framework</p>
            </div>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            className="p-1.5 text-text-secondary hover:text-text-primary transition-colors md:hidden"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="flex-1 p-4 space-y-1">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/' || to === '/admin'}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'bg-accent/10 text-accent'
                    : 'text-text-secondary hover:bg-surface-2 hover:text-text-primary'
                }`
              }
            >
              <Icon className="w-5 h-5" />
              <span className="text-sm font-medium">{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-border-subtle">
          <div className="flex items-center justify-between px-4 py-2">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-text-primary truncate">{user?.email}</p>
            </div>
            <ThemeToggle />
            <button
              onClick={handleLogout}
              className="p-2 text-text-faint hover:text-text-primary transition-colors"
              title="Logout"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden relative z-1">
        {/* Mobile top bar */}
        <div className="flex items-center gap-3 px-4 py-3 bg-surface border-b border-border-subtle md:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1.5 text-text-secondary hover:text-text-primary transition-colors"
          >
            <Menu className="w-6 h-6" />
          </button>
          <div className="flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-accent" />
            <span className="text-sm font-bold text-text-primary">TradingAgents</span>
          </div>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </div>

        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
