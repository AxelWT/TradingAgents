import { useAnalysisStore } from '../../stores/analysisStore'
import { Wrench, MessageSquare } from 'lucide-react'

export default function MessageFeed() {
  const messages = useAnalysisStore((s) => s.messages)
  const toolCalls = useAnalysisStore((s) => s.toolCalls)

  const allItems = [
    ...messages.map((m) => ({ ...m, kind: 'message' as const })),
    ...toolCalls.map((t) => ({ ...t, kind: 'tool' as const })),
  ]
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    .slice(-50)

  return (
    <div className="flex flex-col overflow-hidden">
      <div className="p-4 border-b border-gray-800">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Messages & Tools
        </h3>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-2">
        {allItems.length === 0 ? (
          <div className="text-gray-600 text-sm text-center py-8">
            Waiting for messages...
          </div>
        ) : (
          allItems.map((item, i) => (
            <div key={i} className="text-xs">
              {item.kind === 'tool' ? (
                <div className="flex items-start gap-2 px-2 py-1.5 rounded bg-gray-800/50">
                  <Wrench className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <span className="text-gray-500">{item.timestamp}</span>{' '}
                    <span className="text-amber-300 font-medium">
                      {(item as { tool: string }).tool}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-2 px-2 py-1.5 rounded bg-gray-800/30">
                  <MessageSquare
                    className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${
                      item.type === 'Agent'
                        ? 'text-blue-400'
                        : item.type === 'Data'
                        ? 'text-emerald-400'
                        : 'text-gray-500'
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <span className="text-gray-500">{item.timestamp}</span>{' '}
                    <span className="text-gray-300">{item.content.slice(0, 200)}</span>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
