import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { reportsApi } from '../api/reports'
import { AnalysisTask } from '../api/analysis'
import { FileText, Download, Search, TrendingUp, Trash2 } from 'lucide-react'

export default function Reports() {
  const [tasks, setTasks] = useState<AnalysisTask[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    loadReports()
  }, [page, debouncedSearch])

  const loadReports = async () => {
    setLoading(true)
    try {
      const resp = await reportsApi.list(page, 20, debouncedSearch || undefined)
      setTasks(resp.tasks)
      setTotal(resp.total)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async (taskId: string, ticker: string, date: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    try {
      const content = await reportsApi.download(taskId)
      const blob = new Blob([content], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report_${ticker}_${date}.md`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // ignore
    }
  }

  const handleDelete = async (taskId: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!window.confirm('Delete this report? This action cannot be undone.')) return
    try {
      await reportsApi.delete(taskId)
      await loadReports()
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        window.alert('This analysis is still running and cannot be deleted')
      } else {
        window.alert('Failed to delete, please try again later')
      }
    }
  }

  const signalColor: Record<string, string> = {
    Buy: 'text-emerald-400 bg-emerald-400/10',
    Hold: 'text-yellow-400 bg-yellow-400/10',
    Sell: 'text-red-400 bg-red-400/10',
  }

  return (
    <div className="p-4 md:p-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white">Reports</h1>
          <p className="text-gray-500 mt-1">{total} completed analyses</p>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            className="pl-10 pr-4 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-emerald-500 w-full sm:w-64"
            placeholder="Search by ticker..."
          />
        </div>
      </div>

      {loading ? (
        <div className="text-gray-500 text-center py-12">Loading...</div>
      ) : tasks.length === 0 ? (
        <div className="text-gray-500 text-center py-16 bg-gray-900 rounded-xl border border-gray-800">
          <FileText className="w-12 h-12 mx-auto mb-4 text-gray-600" />
          <p className="text-lg">No reports yet</p>
          <p className="text-sm mt-2">Complete an analysis to see reports here</p>
        </div>
      ) : (
        <div className="space-y-3">
          {tasks.map((task) => (
            <Link
              key={task.id}
              to={`/reports/${task.id}`}
              className="flex flex-wrap items-center justify-between gap-3 p-4 md:p-5 bg-gray-900 border border-gray-800 rounded-xl hover:border-gray-700 transition-colors group"
            >
              <div className="flex items-center gap-3 md:gap-5">
                <div className="p-2.5 bg-gray-800 rounded-lg">
                  <TrendingUp className="w-5 h-5 text-emerald-400" />
                </div>
                <div>
                  <div className="flex items-center gap-3">
                    <span className="text-white font-semibold text-lg">{task.ticker}</span>
                    {task.signal && (
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                          signalColor[task.signal] || 'text-gray-400 bg-gray-800'
                        }`}
                      >
                        {task.signal}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
                    <span>{task.trade_date}</span>
                    <span>|</span>
                    <span>
                      {task.completed_at
                        ? new Date(task.completed_at).toLocaleString()
                        : 'N/A'}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={(e) =>
                    handleDownload(task.id, task.ticker, task.trade_date, e)
                  }
                  className="p-2 text-gray-500 hover:text-emerald-400 transition-colors"
                  title="Download report"
                >
                  <Download className="w-4 h-4" />
                </button>
                <button
                  onClick={(e) => handleDelete(task.id, e)}
                  className="p-2 text-gray-500 hover:text-red-400 transition-colors"
                  title="Delete report"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </Link>
          ))}
        </div>
      )}

      {total > 20 && (
        <div className="flex items-center justify-center gap-3 md:gap-4 mt-6 md:mt-8">
          <button
            disabled={page === 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-300 disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-gray-500 text-sm">
            Page {page} of {Math.ceil(total / 20)}
          </span>
          <button
            disabled={page >= Math.ceil(total / 20)}
            onClick={() => setPage((p) => p + 1)}
            className="px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-300 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
