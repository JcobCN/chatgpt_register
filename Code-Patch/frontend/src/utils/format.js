/**
 * Format an ISO timestamp to a human-readable local string.
 * Returns '—' for null/undefined values.
 */
export function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

/**
 * Map alive status value to an Element Plus tag type.
 */
export function aliveTagType(v) {
  if (v === 'alive') return 'success'
  if (v === 'dead') return 'danger'
  if (v === 'error') return 'warning'
  return 'info'
}

/**
 * Map alive status value to a display label.
 */
export function aliveLabel(v) {
  if (v === 'alive') return '存活'
  if (v === 'dead') return '已失效'
  if (v === 'error') return '检测异常'
  return '未检测'
}
