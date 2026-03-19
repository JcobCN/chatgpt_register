import { ref, reactive, computed } from 'vue'
import { openCheckWS } from '../api/index.js'

// 全局状态 — 模块级别，切换页面不会丢失
const checking = ref(false)
const checkProgress = reactive({ total: 0, done: 0, alive: 0, dead: 0, error: 0 })
let checkWs = null
let onDoneCallback = null

const checkPct = computed(() => {
  if (!checkProgress.total) return 0
  return Math.round((checkProgress.done / checkProgress.total) * 100)
})

function startCheck(checkId, total, { onResult, onDone } = {}) {
  // 关闭之前的连接
  checkWs?.close()

  checking.value = true
  checkProgress.total = total
  checkProgress.done = 0
  checkProgress.alive = 0
  checkProgress.dead = 0
  checkProgress.error = 0
  onDoneCallback = onDone || null

  checkWs = openCheckWS(checkId, {
    onResult(msg) {
      checkProgress.done++
      if (msg.alive === 'alive') checkProgress.alive++
      else if (msg.alive === 'dead') checkProgress.dead++
      else checkProgress.error++
      onResult?.(msg)
    },
    onDone(msg) {
      checking.value = false
      checkWs?.close()
      checkWs = null
      onDoneCallback?.(msg)
    },
    onError() {
      checking.value = false
      checkWs?.close()
      checkWs = null
    },
  })
}

function stopCheck() {
  checkWs?.close()
  checkWs = null
  checking.value = false
}

export function useCheckState() {
  return { checking, checkProgress, checkPct, startCheck, stopCheck }
}
