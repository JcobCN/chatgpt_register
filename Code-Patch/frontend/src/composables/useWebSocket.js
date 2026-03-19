import { onUnmounted } from 'vue'

/**
 * Composable for managing a WebSocket connection.
 * Automatically closes the socket when the component is unmounted.
 *
 * @param {string} path - Path template, e.g. '/ws/sessions/{id}'
 * @param {object} handlers - { onMessage(msg), onError(e) }
 * @returns {{ open(id: string|number): void, close(): void }}
 */
export function useWebSocket(path, handlers = {}) {
  let ws = null

  function open(id) {
    close()
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${location.host}${path.replace('{id}', id)}`
    ws = new WebSocket(url)

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type !== 'ping') {
        handlers.onMessage?.(msg)
      }
    }

    ws.onerror = (e) => handlers.onError?.(e)
  }

  function close() {
    if (ws) {
      ws.close()
      ws = null
    }
  }

  onUnmounted(close)

  return { open, close }
}
