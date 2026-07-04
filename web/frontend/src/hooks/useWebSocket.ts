import { useEffect, useRef, useCallback } from 'react'
import { useAnalysisStore } from '../stores/analysisStore'

const MAX_RETRIES = 5
const BASE_DELAY = 1000

export function useWebSocket(taskId: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const retryCountRef = useRef(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedByUsRef = useRef(false)
  const processWSMessage = useAnalysisStore((s) => s.processWSMessage)

  const connect = useCallback(() => {
    if (!taskId) return

    const token = localStorage.getItem('access_token')
    if (!token) return

    closedByUsRef.current = false

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws/${taskId}?token=${token}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      retryCountRef.current = 0
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
      if (closedByUsRef.current) return
      if (retryCountRef.current >= MAX_RETRIES) {
        console.warn('[WS] Max retries reached, giving up')
        return
      }
      const delay = BASE_DELAY * Math.pow(2, retryCountRef.current)
      retryCountRef.current += 1
      console.log(`[WS] Reconnecting in ${delay}ms (attempt ${retryCountRef.current})`)
      retryTimerRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      // onclose will handle reconnection
    }
  }, [taskId, processWSMessage])

  const disconnect = useCallback(() => {
    closedByUsRef.current = true
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  useEffect(() => {
    if (taskId) {
      retryCountRef.current = 0
      connect()
    }
    return () => {
      disconnect()
    }
  }, [taskId, connect, disconnect])

  return { connect, disconnect }
}
