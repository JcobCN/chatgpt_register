import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 30000 })

// Normalise error messages so callers can use err.message uniformly
http.interceptors.response.use(
  r => r,
  err => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(msg))
  }
)

export const getSystemProxy = () => http.get('/system-proxy')
export const startSession = (data) => http.post('/sessions', data)
export const getSessions = () => http.get('/sessions')
export const getActiveSession = () => http.get('/sessions/active')
export const getAccounts = (params) => http.get('/accounts', { params })
export const getAccount = (id) => http.get(`/accounts/${id}`)

export function exportSessionUrl(sessionId) {
  return `/api/sessions/${sessionId}/export`
}

export function exportAccountsUrl(params = {}) {
  const qs = new URLSearchParams()
  if (params.search) qs.set('search', params.search)
  if (params.status) qs.set('status', params.status)
  if (params.session_id) qs.set('session_id', params.session_id)
  if (params.alive) qs.set('alive', params.alive)
  const q = qs.toString()
  return `/api/accounts/export${q ? '?' + q : ''}`
}

export const pauseSession = (id) => http.post(`/sessions/${id}/pause`)
export const resumeSession = (id) => http.post(`/sessions/${id}/resume`)
export const getSchedules = () => http.get('/schedules')
export const createSchedule = (data) => http.post('/schedules', data)
export const updateSchedule = (id, data) => http.put(`/schedules/${id}`, data)
export const toggleSchedule = (id) => http.put(`/schedules/${id}/toggle`)
export const deleteSchedule = (id) => http.delete(`/schedules/${id}`)
export const getScheduleRuns = (id) => http.get(`/schedules/${id}/runs`)
export const getAllRuns = (limit = 50) => http.get('/schedule-runs', { params: { limit } })

export const startCheckSession = (data) => http.post('/check-sessions', data)
export const importAccounts = (data) => http.post('/accounts/import', data)
export const deleteDeadAccounts = () => http.delete('/accounts/dead')
export const setAutoRefresh = (id, enabled) => http.put(`/accounts/${id}/auto-refresh`, null, { params: { enabled } })

/**
 * Open a WebSocket for a registration session.
 */
export function openSessionWS(sessionId, { onSuccess, onFailed, onDone, onError } = {}) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${proto}//${location.host}/ws/sessions/${sessionId}`)

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.type === 'success') onSuccess?.(msg)
    else if (msg.type === 'failed') onFailed?.(msg)
    else if (msg.type === 'done') onDone?.(msg)
    // ignore 'ping'
  }
  ws.onerror = (e) => onError?.(e)

  return ws
}

/**
 * Open a WebSocket for a liveness check session.
 */
export function openCheckWS(checkId, { onResult, onDone, onError } = {}) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${proto}//${location.host}/ws/check/${checkId}`)

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.type === 'result') onResult?.(msg)
    else if (msg.type === 'done') onDone?.(msg)
    // ignore 'ping'
  }
  ws.onerror = (e) => onError?.(e)

  return ws
}

/**
 * Open a WebSocket for an import session.
 */
export function openImportWS(importId, { onResult, onDone, onError } = {}) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${proto}//${location.host}/ws/sessions/${importId}`)

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.type === 'success') onResult?.({ ...msg, alive: 'alive' })
    else if (msg.type === 'failed') onResult?.({ ...msg, alive: 'dead' })
    else if (msg.type === 'done') onDone?.(msg)
    // ignore 'ping'
  }
  ws.onerror = (e) => onError?.(e)

  return ws
}
