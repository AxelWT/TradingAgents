import { useEffect, useRef, useCallback } from 'react'
import { useAnalysisStore } from '../stores/analysisStore'

export function useWebSocket(taskId: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const processWSMessage = useAnalysisStore((s) => s.processWSMessage)

  const connect = useCallback(() => {
    if (!taskId) return

    const token = localStorage.getItem('access_token')
    if (!token) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws/${taskId}?token=${token}`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[WS] Connected to task', taskId)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        processWSMessage(msg)
      } catch {
        // ignore non-JSON messages
      }
    }

    ws.onclose = () => {
      wsRef.current = null
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [taskId, processWSMessage])

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    if (taskId) {
      connect()
    }
    return () => {
      disconnect()
    }
  }, [taskId, connect, disconnect])

  return { connect, disconnect }
}
