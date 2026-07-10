import { useEffect, useState, useCallback } from 'react'
import { adminApi, AdminUser } from '../../api/admin'
import {
  Search,
  Ban,
  CheckCircle,
  Shield,
  ShieldOff,
  Trash2,
  UserCog,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'

export default function AdminUsers() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const pageSize = 20

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await adminApi.listUsers({
        page,
        page_size: pageSize,
        search: debouncedSearch || undefined,
        status_filter: statusFilter || undefined,
      })
      setUsers(resp.users)
      setTotal(resp.total)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [page, debouncedSearch, statusFilter])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  const handleAction = async (userId: string, action: () => Promise<unknown>) => {
    setActionLoading(userId)
    try {
      await action()
      await loadUsers()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      window.alert(detail || 'Operation failed')
    } finally {
      setActionLoading(null)
    }
  }

  const handleDelete = async (user: AdminUser) => {
    if (
      !window.confirm(
        `Delete user ${user.email}?\nAll analysis tasks and verification codes for this user will be permanently deleted. This action cannot be undone.`
      )
    )
      return
    await handleAction(user.id, () => adminApi.deleteUser(user.id))
  }

  const handleToggleAdmin = async (user: AdminUser) => {
    const newVal = !user.is_admin
    if (
      !window.confirm(
        newVal
          ? `Grant admin privileges to ${user.email}?`
          : `Revoke admin privileges from ${user.email}?`
      )
    )
      return
    await handleAction(user.id, () => adminApi.updateUser(user.id, { is_admin: newVal }))
  }

  const totalPages = Math.ceil(total / pageSize)

  const filters = [
    { value: '', label: 'All' },
    { value: 'active', label: 'Active' },
    { value: 'blacklisted', label: 'Blacklisted' },
    { value: 'whitelisted', label: 'Whitelisted' },
    { value: 'admin', label: 'Admins' },
  ]

  return (
    <div className="p-4 md:p-8 relative z-1">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <div className="section-tag mb-2">Administration</div>
          <h1 className="text-2xl md:text-3xl font-bold text-text-primary" style={{ fontFamily: 'var(--font-serif)' }}>
            User Management
          </h1>
          <p className="text-text-secondary mt-1">{total} registered users</p>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-faint" />
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            className="pl-10 pr-4 py-2.5 bg-surface-2 border border-border-subtle rounded-lg text-text-primary text-sm placeholder-text-faint focus:outline-none focus:border-accent w-full sm:w-64 transition-colors"
            placeholder="Search by email..."
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-6">
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => {
              setStatusFilter(f.value)
              setPage(1)
            }}
            className={`px-4 py-1.5 rounded-lg text-sm transition-colors ${
              statusFilter === f.value
                ? 'bg-accent/10 text-accent border border-accent/30'
                : 'bg-surface-2 text-text-secondary border border-border-subtle hover:text-text-primary hover:border-border-strong'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-text-secondary text-center py-12">Loading...</div>
      ) : users.length === 0 ? (
        <div className="text-text-secondary text-center py-16 bg-surface rounded-xl border border-border-subtle">
          <p>No matching users found</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto bg-surface border border-border-subtle rounded-xl">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-subtle text-text-faint">
                  <th className="text-left px-4 py-3 font-medium">Email</th>
                  <th className="text-left px-4 py-3 font-medium">Registered</th>
                  <th className="text-left px-4 py-3 font-medium">Tasks</th>
                  <th className="text-left px-4 py-3 font-medium">Status</th>
                  <th className="text-right px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr
                    key={user.id}
                    className="border-b border-border-subtle/50 hover:bg-surface-2/30 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-text-primary">{user.email}</span>
                        {user.is_admin && (
                          <span className="px-2 py-0.5 rounded-full text-xs font-medium text-yellow-400 bg-yellow-400/10">
                            Admin
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {user.created_at
                        ? new Date(user.created_at).toLocaleDateString()
                        : '-'}
                    </td>
                    <td className="px-4 py-3 text-text-secondary" style={{ fontFamily: 'var(--font-mono)' }}>
                      {user.task_count}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {user.is_active ? (
                          <span className="px-2 py-0.5 rounded-full text-xs font-medium text-emerald-400 bg-emerald-400/10">
                            Active
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-xs font-medium text-red-400 bg-red-400/10">
                            Blacklisted
                          </span>
                        )}
                        {user.is_whitelisted && (
                          <span className="px-2 py-0.5 rounded-full text-xs font-medium text-purple-400 bg-purple-400/10">
                            Whitelisted
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {actionLoading === user.id ? (
                          <span className="text-text-faint text-xs px-2">Processing...</span>
                        ) : (
                          <>
                            {!user.is_admin && (
                              <>
                                {user.is_active ? (
                                  <button
                                    onClick={() =>
                                      handleAction(user.id, () =>
                                        adminApi.addToBlacklist(user.id)
                                      )
                                    }
                                    className="p-1.5 text-text-faint hover:text-red-400 transition-colors"
                                    title="Add to blacklist"
                                  >
                                    <Ban className="w-4 h-4" />
                                  </button>
                                ) : (
                                  <button
                                    onClick={() =>
                                      handleAction(user.id, () =>
                                        adminApi.removeFromBlacklist(user.id)
                                      )
                                    }
                                    className="p-1.5 text-text-faint hover:text-emerald-400 transition-colors"
                                    title="Remove from blacklist"
                                  >
                                    <CheckCircle className="w-4 h-4" />
                                  </button>
                                )}
                                {user.is_whitelisted ? (
                                  <button
                                    onClick={() =>
                                      handleAction(user.id, () =>
                                        adminApi.removeFromWhitelist(user.id)
                                      )
                                    }
                                    className="p-1.5 text-text-faint hover:text-text-primary transition-colors"
                                    title="Remove from whitelist"
                                  >
                                    <ShieldOff className="w-4 h-4" />
                                  </button>
                                ) : (
                                  <button
                                    onClick={() =>
                                      handleAction(user.id, () =>
                                        adminApi.addToWhitelist(user.id)
                                      )
                                    }
                                    className="p-1.5 text-text-faint hover:text-purple-400 transition-colors"
                                    title="Add to whitelist"
                                  >
                                    <Shield className="w-4 h-4" />
                                  </button>
                                )}
                              </>
                            )}
                            <button
                              onClick={() => handleToggleAdmin(user)}
                              className="p-1.5 text-text-faint hover:text-yellow-400 transition-colors"
                              title={user.is_admin ? 'Revoke admin' : 'Grant admin'}
                            >
                              <UserCog className="w-4 h-4" />
                            </button>
                            {!user.is_admin && (
                              <button
                                onClick={() => handleDelete(user)}
                                className="p-1.5 text-text-faint hover:text-red-400 transition-colors"
                                title="Delete user"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 mt-6">
              <button
                disabled={page === 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="p-2 bg-surface-2 border border-border-subtle rounded-lg text-text-secondary disabled:opacity-50 hover:border-border-strong transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-text-faint text-sm">
                Page {page} of {totalPages}
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
                className="p-2 bg-surface-2 border border-border-subtle rounded-lg text-text-secondary disabled:opacity-50 hover:border-border-strong transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
