import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { scheduledJobsApi, type ScheduledJob, type ScheduledJobCreateParams } from '../../api/admin'
import Select from '../../components/ui/Select'
import {
  Clock,
  Plus,
  Trash2,
  Play,
  Power,
  Pencil,
  AlertCircle,
  X,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'

const LLM_PROVIDERS = [{ value: 'deepseek', label: 'DeepSeek' }]

const ANALYST_OPTIONS = [
  { value: 'market', label: 'Market Analyst' },
  { value: 'social', label: 'Sentiment Analyst' },
  { value: 'news', label: 'News Analyst' },
  { value: 'fundamentals', label: 'Fundamentals Analyst' },
]

const DEPTH_OPTIONS = [
  { value: 1, label: 'Quick (1 round)' },
  { value: 2, label: 'Standard (2 rounds)' },
  { value: 3, label: 'Deep (3 rounds)' },
  { value: 4, label: 'Very Deep (4 rounds)' },
]

const OUTPUT_LANGUAGES = [
  { value: 'Chinese', label: 'Chinese' },
  { value: 'English', label: 'English' },
]

const CRON_PRESETS = [
  { label: 'Every weekday 09:30', value: '30 9 * * 1-5' },
  { label: 'Every day 09:30', value: '30 9 * * *' },
  { label: 'Every Monday 09:00', value: '0 9 * * 1' },
  { label: 'Every hour', value: '0 * * * *' },
]

const DEFAULT_FORM: ScheduledJobCreateParams = {
  name: '',
  ticker: '',
  asset_type: 'stock',
  analysts: ['market', 'social', 'news', 'fundamentals'],
  research_depth: 2,
  llm_provider: 'deepseek',
  output_language: 'Chinese',
  cron_expr: '30 9 * * 1-5',
  enabled: true,
}

function formatDateTime(s: string | null): string {
  if (!s) return '-'
  try {
    return new Date(s).toLocaleString()
  } catch {
    return s
  }
}

export default function AdminScheduledJobs() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingJob, setEditingJob] = useState<ScheduledJob | null>(null)

  const pageSize = 20

  const loadJobs = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await scheduledJobsApi.list(page, pageSize)
      setJobs(resp.jobs)
      setTotal(resp.total)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [page])

  useEffect(() => {
    loadJobs()
  }, [loadJobs])

  const handleAction = async (jobId: string, action: () => Promise<unknown>) => {
    setActionLoading(jobId)
    try {
      await action()
      await loadJobs()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      window.alert(detail || 'Operation failed')
    } finally {
      setActionLoading(null)
    }
  }

  const handleToggleEnabled = (job: ScheduledJob) => {
    handleAction(job.id, () => scheduledJobsApi.update(job.id, { enabled: !job.enabled }))
  }

  const handleRun = async (job: ScheduledJob) => {
    if (!window.confirm(`Run "${job.name}" (${job.ticker}) now?`)) return
    await handleAction(job.id, () => scheduledJobsApi.run(job.id))
  }

  const handleDelete = async (job: ScheduledJob) => {
    if (!window.confirm(`Delete scheduled job "${job.name}"? This cannot be undone.`)) return
    await handleAction(job.id, () => scheduledJobsApi.delete(job.id))
  }

  const openCreate = () => {
    setEditingJob(null)
    setShowForm(true)
  }

  const openEdit = (job: ScheduledJob) => {
    setEditingJob(job)
    setShowForm(true)
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="p-4 md:p-8 relative z-1">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <div className="section-tag mb-2">Administration</div>
          <h1
            className="text-2xl md:text-3xl font-bold text-text-primary"
            style={{ fontFamily: 'var(--font-serif)' }}
          >
            Scheduled Reports
          </h1>
          <p className="text-text-secondary mt-1">
            {total} scheduled job{total !== 1 ? 's' : ''} · auto-generated analysis reports
          </p>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-accent to-accent-2 hover:opacity-90 text-bg font-medium rounded-lg transition-opacity"
        >
          <Plus className="w-4 h-4" />
          New Scheduled Job
        </button>
      </div>

      {loading ? (
        <div className="text-text-secondary text-center py-12">Loading...</div>
      ) : jobs.length === 0 ? (
        <div className="text-text-secondary text-center py-16 bg-surface rounded-xl border border-border-subtle">
          <Clock className="w-10 h-10 mx-auto mb-3 text-text-faint" />
          <p>No scheduled jobs yet</p>
          <p className="text-sm text-text-faint mt-1">
            Create a job to automatically generate reports for a ticker on a schedule.
          </p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto bg-surface border border-border-subtle rounded-xl">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-subtle text-text-faint">
                  <th className="text-left px-4 py-3 font-medium">Name / Ticker</th>
                  <th className="text-left px-4 py-3 font-medium">Cron</th>
                  <th className="text-left px-4 py-3 font-medium">Next Run</th>
                  <th className="text-left px-4 py-3 font-medium">Last Run</th>
                  <th className="text-left px-4 py-3 font-medium">Status</th>
                  <th className="text-right px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr
                    key={job.id}
                    className="border-b border-border-subtle/50 hover:bg-surface-2/30 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="text-text-primary font-medium">{job.name}</div>
                      <div className="text-text-faint text-xs" style={{ fontFamily: 'var(--font-mono)' }}>
                        {job.ticker}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-text-secondary" style={{ fontFamily: 'var(--font-mono)' }}>
                      {job.cron_expr}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">{formatDateTime(job.next_run_at)}</td>
                    <td className="px-4 py-3 text-text-secondary">
                      {job.last_task_id ? (
                        <Link
                          to={`/reports/${job.last_task_id}`}
                          className="text-accent hover:underline"
                        >
                          {formatDateTime(job.last_run_at)}
                        </Link>
                      ) : (
                        formatDateTime(job.last_run_at)
                      )}
                      {job.last_error && (
                        <div
                          className="text-down text-xs mt-0.5 flex items-center gap-1"
                          title={job.last_error}
                        >
                          <AlertCircle className="w-3 h-3 shrink-0" />
                          <span className="truncate max-w-[12rem]">{job.last_error}</span>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          job.enabled
                            ? 'text-up bg-up/10'
                            : 'text-text-faint bg-surface-2'
                        }`}
                      >
                        {job.enabled ? 'Active' : 'Paused'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {actionLoading === job.id ? (
                          <span className="text-text-faint text-xs px-2">Processing...</span>
                        ) : (
                          <>
                            <button
                              onClick={() => handleRun(job)}
                              className="p-1.5 text-text-faint hover:text-accent transition-colors"
                              title="Run now"
                            >
                              <Play className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => openEdit(job)}
                              className="p-1.5 text-text-faint hover:text-text-primary transition-colors"
                              title="Edit"
                            >
                              <Pencil className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleToggleEnabled(job)}
                              className="p-1.5 text-text-faint hover:text-yellow-400 transition-colors"
                              title={job.enabled ? 'Pause' : 'Resume'}
                            >
                              <Power className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDelete(job)}
                              className="p-1.5 text-text-faint hover:text-down transition-colors"
                              title="Delete"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
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

      {showForm && (
        <JobFormModal
          job={editingJob}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            loadJobs()
          }}
        />
      )}
    </div>
  )
}

interface JobFormModalProps {
  job: ScheduledJob | null
  onClose: () => void
  onSaved: () => void
}

function JobFormModal({ job, onClose, onSaved }: JobFormModalProps) {
  const [form, setForm] = useState<ScheduledJobCreateParams>(() =>
    job
      ? {
          name: job.name,
          ticker: job.ticker,
          asset_type: job.asset_type,
          analysts: job.analysts ?? ['market', 'social', 'news', 'fundamentals'],
          research_depth: job.research_depth,
          llm_provider: job.llm_provider,
          backend_url: job.backend_url ?? undefined,
          quick_think_llm: job.quick_think_llm ?? undefined,
          deep_think_llm: job.deep_think_llm ?? undefined,
          output_language: job.output_language,
          google_thinking_level: job.google_thinking_level ?? undefined,
          openai_reasoning_effort: job.openai_reasoning_effort ?? undefined,
          anthropic_effort: job.anthropic_effort ?? undefined,
          cron_expr: job.cron_expr,
          enabled: job.enabled,
        }
      : { ...DEFAULT_FORM }
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const toggleAnalyst = (value: string) => {
    setForm((prev) => ({
      ...prev,
      analysts: prev.analysts?.includes(value)
        ? prev.analysts.filter((a) => a !== value)
        : [...(prev.analysts ?? []), value],
    }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.analysts || form.analysts.length === 0) {
      setError('At least one analyst must be selected')
      return
    }
    setLoading(true)
    setError('')
    try {
      if (job) {
        await scheduledJobsApi.update(job.id, form)
      } else {
        await scheduledJobsApi.create(form)
      }
      onSaved()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to save job')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-surface border border-border-subtle rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-6 border-b border-border-subtle sticky top-0 bg-surface">
          <h2 className="text-lg font-bold text-text-primary">
            {job ? 'Edit Scheduled Job' : 'New Scheduled Job'}
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 text-text-faint hover:text-text-primary transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {error && (
            <div className="flex items-center gap-2 p-3 bg-down/10 border border-down/20 rounded-lg text-down text-sm">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-2">
              Job Name <span className="text-down">*</span>
            </label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full px-4 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
              placeholder="e.g. NVDA daily report"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-2">
              Ticker Symbol <span className="text-down">*</span>
            </label>
            <input
              type="text"
              value={form.ticker}
              onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })}
              className="w-full px-4 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
              placeholder="e.g. AAPL, 0700.HK, BTC-USD"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-2">
              Cron Expression <span className="text-down">*</span>
            </label>
            <input
              type="text"
              value={form.cron_expr}
              onChange={(e) => setForm({ ...form, cron_expr: e.target.value })}
              className="w-full px-4 py-3 bg-surface-2 border border-border-subtle rounded-lg text-text-primary placeholder-text-faint focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-colors"
              placeholder="min hour day month weekday (e.g. 30 9 * * 1-5)"
              required
              style={{ fontFamily: 'var(--font-mono)' }}
            />
            <div className="flex flex-wrap gap-2 mt-2">
              {CRON_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  type="button"
                  onClick={() => setForm({ ...form, cron_expr: preset.value })}
                  className="px-3 py-1 bg-surface-2 border border-border-subtle rounded-lg text-xs text-text-secondary hover:border-accent/50 hover:text-text-primary transition-colors"
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-text-faint mt-2">
              Format: minute hour day-of-month month day-of-week (server timezone is UTC). The
              analysis date is set to the run day.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-3">Analyst Team</label>
            <div className="grid grid-cols-2 gap-2">
              {ANALYST_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => toggleAnalyst(value)}
                  className={`px-3 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                    form.analysts?.includes(value)
                      ? 'bg-accent/10 border-accent/50 text-accent'
                      : 'bg-surface-2 border-border-subtle text-text-secondary hover:border-border-strong'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-3">Research Depth</label>
            <div className="grid grid-cols-2 gap-2">
              {DEPTH_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setForm({ ...form, research_depth: value })}
                  className={`px-3 py-2.5 rounded-lg border text-sm font-medium transition-colors ${
                    form.research_depth === value
                      ? 'bg-accent/10 border-accent/50 text-accent'
                      : 'bg-surface-2 border-border-subtle text-text-secondary hover:border-border-strong'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-2">LLM Provider</label>
              <Select
                value={form.llm_provider ?? 'deepseek'}
                options={LLM_PROVIDERS}
                onChange={(v) => setForm({ ...form, llm_provider: v })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-2">Output Language</label>
              <Select
                value={form.output_language ?? 'Chinese'}
                options={OUTPUT_LANGUAGES}
                onChange={(v) => setForm({ ...form, output_language: v })}
              />
            </div>
          </div>

          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={form.enabled ?? true}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              className="w-4 h-4 rounded accent-accent"
            />
            <span className="text-sm text-text-secondary">Enabled (run on schedule)</span>
          </label>

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 bg-surface-2 border border-border-subtle rounded-lg text-text-secondary hover:text-text-primary transition-colors text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-accent to-accent-2 hover:opacity-90 disabled:opacity-50 text-bg font-medium rounded-lg transition-opacity text-sm"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {job ? 'Save Changes' : 'Create Job'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
