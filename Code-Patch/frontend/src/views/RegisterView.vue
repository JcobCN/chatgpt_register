<template>
  <div>
    <el-card class="form-card">
      <template #header>
        <span class="card-title">批量注册</span>
      </template>

      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px" :disabled="status === 'running' || status === 'paused'">
        <el-form-item label="代理池" prop="proxies">
          <el-input
            v-model="form.proxies"
            type="textarea"
            :rows="5"
            placeholder="每行一个代理地址，例如：&#10;http://user:pass@host:port&#10;http://host2:port"
            class="proxy-textarea"
          />
          <div class="field-hint">
            注册时随机选取代理，多代理可提高成功率
            <el-text v-if="proxyCount > 0" type="primary" size="small" style="margin-left:8px;">已输入 {{ proxyCount }} 个代理</el-text>
          </div>
        </el-form-item>

        <el-form-item label="目标数量" prop="count">
          <el-input-number v-model="form.count" :min="1" :max="1000000" />
        </el-form-item>

        <el-form-item label="并发数">
          <el-input-number v-model="form.concurrency" :min="1" :max="1000" />
          <el-tooltip content="并发越高速度越快，但失败率可能上升" placement="right">
            <el-icon class="tip-icon"><QuestionFilled /></el-icon>
          </el-tooltip>
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            :loading="status === 'running'"
            @click="startRegistration"
          >
            <el-icon v-if="status !== 'running'"><UserFilled /></el-icon>
            {{ status === 'running' ? '注册中...' : '开始注册' }}
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="status === 'running' || status === 'paused' || (status === 'done' && sessionId)" class="action-bar">
        <el-button
          v-if="status === 'running'"
          type="warning"
          @click="togglePause"
        >
          <el-icon><VideoPause /></el-icon>
          暂停
        </el-button>
        <el-button
          v-if="status === 'paused'"
          type="success"
          @click="togglePause"
        >
          <el-icon><VideoPlay /></el-icon>
          继续
        </el-button>
        <el-button
          v-if="status === 'done' && sessionId"
          type="success"
          @click="exportCsv"
        >
          <el-icon><Download /></el-icon>
          导出本次 CSV
        </el-button>
      </div>
    </el-card>

    <!-- Progress -->
    <el-card v-if="status !== 'idle'" style="margin-top: 16px;">
      <template #header>
        <div class="progress-header">
          <div class="progress-title">
            <span class="card-title">进度</span>
            <el-tag v-if="status === 'running'" type="warning" size="small">运行中</el-tag>
            <el-tag v-else-if="status === 'paused'" type="info" size="small">已暂停</el-tag>
            <el-tag v-else type="success" size="small">已完成</el-tag>
          </div>
        </div>
      </template>

      <div class="progress-info">
        <span class="progress-text">
          <span class="progress-current">{{ progress.success }}</span>
          <span class="progress-sep"> / </span>
          <span class="progress-target">{{ targetCount }}</span>
        </span>
        <span class="progress-detail">
          失败 {{ progress.failed }}
          <template v-if="progress.success + progress.failed > 0">
            · 成功率 {{ successRate }}%
          </template>
        </span>
      </div>
      <el-progress
        :percentage="progressPct"
        :status="status === 'done' ? 'success' : ''"
        :stroke-width="12"
        :show-text="false"
        style="margin-bottom: 16px;"
      />

      <!-- Log terminal -->
      <div class="log-header">
        <span class="log-title">实时日志</span>
        <div class="log-controls">
          <el-switch
            v-model="autoScroll"
            size="small"
            active-text="自动滚动"
            inactive-text=""
            style="margin-right: 12px;"
          />
          <el-button size="small" text @click="logs = []">
            <el-icon><Delete /></el-icon>
            清空
          </el-button>
        </div>
      </div>
      <div ref="logEl" class="log-terminal">
        <div
          v-for="(line, i) in logs"
          :key="i"
          :class="['log-line', line.type === 'success' ? 'log-success' : 'log-failed']"
        >
          <span class="log-time">{{ line.time }} </span>
          <span class="log-level">{{ line.type === 'success' ? 'SUCCESS' : 'FAILED ' }}</span>
          &nbsp;{{ line.text }}
        </div>
        <div v-if="logs.length === 0" class="log-empty">等待任务开始...</div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { startSession, pauseSession, resumeSession, openSessionWS, exportSessionUrl, getSystemProxy, getActiveSession } from '../api/index.js'

const formRef = ref(null)
const savedProxies = localStorage.getItem('register_proxies') || ''
const form = ref({ proxies: savedProxies, count: 5, concurrency: 3 })
const autoScroll = ref(true)

const rules = {
  proxies: [{ required: true, message: '请填写至少一个代理地址', trigger: 'blur' }],
  count: [{ type: 'number', min: 1, message: '注册数量需 ≥ 1', trigger: 'change' }],
}

const proxyCount = computed(() =>
  form.value.proxies.split('\n').filter(l => l.trim()).length
)

watch(() => form.value.proxies, (v) => {
  localStorage.setItem('register_proxies', v)
})

onMounted(async () => {
  try {
    const resp = await getSystemProxy()
    if (resp.data.proxy && !form.value.proxies) form.value.proxies = resp.data.proxy
  } catch {}

  // 恢复运行中/暂停的任务
  try {
    const resp = await getActiveSession()
    const s = resp.data.session
    if (s) {
      sessionId.value = s.id
      targetCount.value = s.requested
      progress.value = { success: s.success, failed: s.failed }
      status.value = s.status === 'paused' ? 'paused' : 'running'
      connectWS(s.id)
    }
  } catch {}
})

const status = ref('idle')   // idle | running | paused | done
const sessionId = ref(null)
const targetCount = ref(0)
const progress = ref({ success: 0, failed: 0 })
const logs = ref([])
const logEl = ref(null)
let ws = null

const progressPct = computed(() => {
  if (!targetCount.value) return 0
  return Math.min(100, Math.round((progress.value.success / targetCount.value) * 100))
})

const successRate = computed(() => {
  const total = progress.value.success + progress.value.failed
  if (total === 0) return 0
  return Math.round((progress.value.success / total) * 100)
})

function timestamp() {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function scrollLog() {
  if (!autoScroll.value) return
  nextTick(() => {
    if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
  })
}

function connectWS(sid) {
  ws?.close()
  ws = openSessionWS(sid, {
    onSuccess(msg) {
      progress.value.success++
      logs.value.push({
        type: 'success',
        time: timestamp(),
        text: `${msg.email}  [${msg.proxy}]  (${msg.elapsed}s)`,
      })
      scrollLog()
    },
    onFailed(msg) {
      progress.value.failed++
      logs.value.push({
        type: 'failed',
        time: timestamp(),
        text: `${msg.error}  [${msg.proxy}]  (${msg.elapsed}s)`,
      })
      scrollLog()
    },
    onDone(msg) {
      status.value = 'done'
      progress.value.success = msg.success
      progress.value.failed = msg.failed
      ElMessage.success(`注册完成：成功 ${msg.success}，失败 ${msg.failed}`)
      ws?.close()
    },
    onError() {
      ElMessage.error('WebSocket 连接异常')
      status.value = 'done'
    },
  })
}

async function startRegistration() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  status.value = 'running'
  logs.value = []
  progress.value = { success: 0, failed: 0 }
  sessionId.value = null
  targetCount.value = form.value.count

  try {
    const resp = await startSession({
      proxies: form.value.proxies,
      count: form.value.count,
      concurrency: form.value.concurrency,
    })
    sessionId.value = resp.data.session_id
    connectWS(sessionId.value)
  } catch (err) {
    status.value = 'idle'
    ElMessage.error(err.message)
  }
}

async function togglePause() {
  if (!sessionId.value) return
  try {
    if (status.value === 'running') {
      await pauseSession(sessionId.value)
      status.value = 'paused'
      ElMessage.info('已暂停')
    } else if (status.value === 'paused') {
      await resumeSession(sessionId.value)
      status.value = 'running'
      ElMessage.success('已恢复')
    }
  } catch (err) {
    ElMessage.error(err.message)
  }
}

function exportCsv() {
  window.open(exportSessionUrl(sessionId.value))
}

onUnmounted(() => {
  // 只关闭 WS 连接，不影响后端任务继续运行
  ws?.close()
})
</script>

<style scoped>
.form-card { max-width: 800px; }

.action-bar {
  display: flex;
  gap: 8px;
  padding: 0 0 0 100px;
}

.card-title { font-weight: 600; }

.proxy-textarea :deep(textarea) {
  font-family: var(--font-mono);
  font-size: 13px;
}

.field-hint {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
  line-height: 1.5;
}

.tip-icon {
  margin-left: 8px;
  color: #909399;
  cursor: help;
  font-size: 16px;
}

.progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.progress-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.log-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
}

.log-controls {
  display: flex;
  align-items: center;
}

.log-terminal {
  background: var(--color-log-bg);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  height: 320px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.7;
}

.log-line { margin: 0; }

.log-success { color: var(--color-log-success); }
.log-failed  { color: var(--color-log-failed); }

.log-time {
  color: var(--color-log-meta);
  user-select: none;
}

.log-level {
  font-weight: 600;
}

.log-empty {
  color: #484f58;
}

.progress-info {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 8px;
}

.progress-text {
  font-size: 24px;
  font-weight: 700;
}

.progress-current {
  color: #67c23a;
}

.progress-sep {
  color: #909399;
  margin: 0 2px;
}

.progress-target {
  color: #303133;
}

.progress-detail {
  font-size: 13px;
  color: #909399;
}
</style>
