<template>
  <div>
    <div class="page-header">
      <span class="page-title">任务中心</span>
      <el-button type="primary" @click="openDialog(null)">
        <el-icon><Plus /></el-icon>
        新建任务
      </el-button>
    </div>

    <el-card>
      <el-table :data="schedules" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="55" />
        <el-table-column prop="name" label="任务名称" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.name || '未命名' }}</template>
        </el-table-column>
        <el-table-column label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.schedule_type === 'daily' ? 'primary' : 'info'" size="small">
              {{ row.schedule_type === 'daily' ? '每天' : '单次' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="任务类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="taskTypeTag(row.task_type || 'register')" size="small">
              {{ taskTypeLabel(row.task_type || 'register') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="执行时间" width="170">
          <template #default="{ row }">
            <span v-if="row.schedule_type === 'daily'">每天 {{ row.run_time }}</span>
            <span v-else>{{ formatTime(row.run_time) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="目标/范围" width="130" align="center">
          <template #default="{ row }">
            <span v-if="(row.task_type || 'register') === 'register'">{{ row.target }}</span>
            <span v-else-if="row.task_type === 'clean'" style="color:#909399;">自动</span>
            <template v-else>
              <el-tag size="small" type="info">
                {{ {all:'全部', alive:'存活', unchecked:'未检测'}[row.check_filter] || '全部' }}
              </el-tag>
              <span v-if="row.check_limit > 0" style="margin-left:4px; font-size:12px; color:#909399;">
                ×{{ row.check_limit }}
              </span>
            </template>
          </template>
        </el-table-column>
        <el-table-column prop="concurrency" label="并发" width="60" align="center" />
        <el-table-column label="下次执行" width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.enabled && row.next_run">{{ formatTime(row.next_run) }}</span>
            <span v-else style="color:#c0c4cc;">--</span>
          </template>
        </el-table-column>
        <el-table-column label="上次执行" width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.last_run_at">{{ formatTime(row.last_run_at) }}</span>
            <span v-else style="color:#c0c4cc;">--</span>
          </template>
        </el-table-column>
        <el-table-column label="上次批次" width="80" align="center">
          <template #default="{ row }">
            <router-link
              v-if="row.last_session_id"
              :to="'/sessions'"
              class="session-link"
            >#{{ row.last_session_id }}</router-link>
            <span v-else style="color:#c0c4cc;">--</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" align="center">
          <template #default="{ row }">
            <el-button
              :type="row.enabled ? 'warning' : 'success'"
              size="small"
              @click="toggle(row)"
            >
              {{ row.enabled ? '停用' : '启用' }}
            </el-button>
            <el-button size="small" @click="openDialog(row)">编辑</el-button>
            <el-button type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="暂无定时任务">
            <el-button type="primary" @click="openDialog(null)">创建第一个</el-button>
          </el-empty>
        </template>
      </el-table>
    </el-card>

    <!-- 执行记录 -->
    <el-card style="margin-top:16px;">
      <template #header>
        <div style="display:flex; align-items:center; justify-content:space-between;">
          <span style="font-weight:600;">执行记录</span>
          <el-button size="small" @click="loadRuns">刷新</el-button>
        </div>
      </template>
      <el-table :data="runs" v-loading="runsLoading" stripe size="small">
        <el-table-column prop="id" label="ID" width="55" />
        <el-table-column label="任务" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.schedule_name || `#${row.schedule_id}` }}
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="taskTypeTag(row.task_type)" size="small">{{ taskTypeLabel(row.task_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="170">
          <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="结束时间" width="170">
          <template #default="{ row }">
            <span v-if="row.finished_at">{{ formatTime(row.finished_at) }}</span>
            <span v-else style="color:#e6a23c;">运行中...</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="runStatusTag(row.status)" size="small">{{ runStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="详情" min-width="250">
          <template #default="{ row }">
            <div v-if="row.status === 'running' && parseProgress(row.detail)">
              <div style="display:flex; align-items:center; gap:8px;">
                <el-progress
                  :percentage="parseProgress(row.detail).pct"
                  :stroke-width="14"
                  :text-inside="true"
                  style="flex:1;"
                />
              </div>
              <div style="font-size:12px; color:#909399; margin-top:2px;">{{ row.detail }}</div>
            </div>
            <span v-else>{{ row.detail || '—' }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无执行记录" :image-size="60" />
        </template>
      </el-table>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑定时任务' : '新建定时任务'"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form :model="formData" label-width="90px">
        <el-form-item label="任务名称">
          <el-input v-model="formData.name" placeholder="可选，便于识别" />
        </el-form-item>
        <el-form-item label="任务类型">
          <el-radio-group v-model="formData.task_type">
            <el-radio value="register">注册账号</el-radio>
            <el-radio value="check">检测存活</el-radio>
            <el-radio value="refresh">刷新Token</el-radio>
            <el-radio value="clean">清理失效</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="执行方式">
          <el-radio-group v-model="formData.schedule_type">
            <el-radio value="once">单次</el-radio>
            <el-radio value="daily">每天</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="执行时间">
          <el-date-picker
            v-if="formData.schedule_type === 'once'"
            v-model="formData.run_time_once"
            type="datetime"
            placeholder="选择日期时间"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width:100%;"
          />
          <el-time-picker
            v-else
            v-model="formData.run_time_daily"
            placeholder="选择时间"
            format="HH:mm"
            value-format="HH:mm"
            style="width:220px;"
          />
        </el-form-item>
        <el-form-item v-if="formData.task_type !== 'clean'" label="代理池">
          <el-input
            v-model="formData.proxies"
            type="textarea"
            :rows="3"
            placeholder="每行一个代理地址"
            class="mono-input"
          />
        </el-form-item>
        <el-form-item v-if="formData.task_type === 'register'" label="目标数量">
          <el-input-number v-model="formData.target" :min="1" :max="1000000" />
        </el-form-item>
        <el-form-item v-if="formData.task_type === 'check'" label="检测范围">
          <el-select v-model="formData.check_filter" style="width:220px;">
            <el-option value="all" label="全部成功账号" />
            <el-option value="alive" label="仅存活账号" />
            <el-option value="unchecked" label="仅未检测账号" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="formData.task_type === 'check' || formData.task_type === 'refresh'" label="数量限制">
          <el-input-number v-model="formData.check_limit" :min="0" :max="1000000" />
          <span style="margin-left:8px; font-size:12px; color:#909399;">0 = 全部</span>
        </el-form-item>
        <el-form-item v-if="formData.task_type === 'check'" label="自动清理">
          <el-checkbox v-model="formData.auto_clean">检测后删除失效账号</el-checkbox>
        </el-form-item>
        <el-form-item v-if="formData.task_type !== 'clean'" label="并发数">
          <el-input-number v-model="formData.concurrency" :min="1" :max="1000" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getSchedules, createSchedule, updateSchedule, toggleSchedule, deleteSchedule,
  getSystemProxy, getScheduleRuns, getAllRuns,
} from '../api/index.js'
import { formatTime } from '../utils/format.js'

const schedules = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref(null)

const formData = reactive({
  name: '',
  task_type: 'register',
  schedule_type: 'daily',
  run_time_once: '',
  run_time_daily: '08:00',
  proxies: '',
  target: 10,
  concurrency: 3,
  check_filter: 'all',
  check_limit: 0,
  auto_clean: false,
})

let defaultProxies = ''

async function loadSchedules() {
  loading.value = true
  try {
    const resp = await getSchedules()
    schedules.value = resp.data
  } finally {
    loading.value = false
  }
}

function openDialog(row) {
  if (row) {
    editingId.value = row.id
    formData.name = row.name || ''
    formData.task_type = row.task_type || 'register'
    formData.schedule_type = row.schedule_type
    formData.proxies = row.proxies || ''
    formData.target = row.target
    formData.concurrency = row.concurrency
    formData.check_filter = row.check_filter || 'all'
    formData.check_limit = row.check_limit || 0
    formData.auto_clean = !!row.auto_clean
    if (row.schedule_type === 'daily') {
      formData.run_time_daily = row.run_time
      formData.run_time_once = ''
    } else {
      formData.run_time_once = row.run_time
      formData.run_time_daily = '08:00'
    }
  } else {
    editingId.value = null
    formData.name = ''
    formData.task_type = 'register'
    formData.schedule_type = 'daily'
    formData.run_time_once = ''
    formData.run_time_daily = '08:00'
    formData.proxies = defaultProxies
    formData.target = 10
    formData.concurrency = 3
    formData.check_filter = 'all'
    formData.check_limit = 0
    formData.auto_clean = false
  }
  dialogVisible.value = true
}

async function save() {
  const run_time = formData.schedule_type === 'daily'
    ? formData.run_time_daily
    : formData.run_time_once
  if (!run_time) {
    ElMessage.warning('请选择执行时间')
    return
  }
  if (formData.task_type !== 'clean' && !formData.proxies.trim()) {
    ElMessage.warning('请填写代理池')
    return
  }

  saving.value = true
  const payload = {
    name: formData.name,
    task_type: formData.task_type,
    proxies: formData.proxies,
    target: formData.target,
    concurrency: formData.concurrency,
    check_filter: formData.check_filter,
    check_limit: formData.check_limit,
    auto_clean: formData.auto_clean,
    schedule_type: formData.schedule_type,
    run_time,
  }
  try {
    if (editingId.value) {
      await updateSchedule(editingId.value, payload)
      ElMessage.success('已更新')
    } else {
      await createSchedule(payload)
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    await loadSchedules()
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    saving.value = false
  }
}

async function toggle(row) {
  try {
    const resp = await toggleSchedule(row.id)
    ElMessage.success(resp.data.enabled ? '已启用' : '已停用')
    await loadSchedules()
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除任务「${row.name || '#' + row.id}」？`,
      '删除确认',
      { type: 'warning' },
    )
    await deleteSchedule(row.id)
    ElMessage.success('已删除')
    await loadSchedules()
  } catch {}
}

const TASK_TYPE_MAP = {
  register: { label: '注册', tag: 'success' },
  check: { label: '检测存活', tag: 'warning' },
  refresh: { label: '刷新Token', tag: '' },
  clean: { label: '清理失效', tag: 'danger' },
}
function taskTypeLabel(t) { return TASK_TYPE_MAP[t]?.label || t }
function taskTypeTag(t) { return TASK_TYPE_MAP[t]?.tag || 'info' }

function runStatusLabel(s) {
  return { running: '运行中', done: '完成', failed: '失败' }[s] || s
}
function runStatusTag(s) {
  return { running: 'warning', done: 'success', failed: 'danger' }[s] || 'info'
}

const runs = ref([])
const runsLoading = ref(false)

async function loadRuns() {
  runsLoading.value = true
  try {
    const resp = await getAllRuns(50)
    runs.value = resp.data
  } finally {
    runsLoading.value = false
  }
}

function parseProgress(detail) {
  if (!detail) return null
  // 匹配 "成功 3 / 目标 10" 或 "已检测 5 / 20" 或 "已刷新 5 / 20"
  const m = detail.match(/(\d+)\s*\/\s*(?:目标\s*)?(\d+)/)
  if (!m) return null
  const current = parseInt(m[1])
  const total = parseInt(m[2])
  if (total <= 0) return null
  return { current, total, pct: Math.min(Math.round(current / total * 100), 100) }
}

let runsTimer = null

function startRunsPolling() {
  stopRunsPolling()
  runsTimer = setInterval(() => {
    if (runs.value.some(r => r.status === 'running')) {
      loadRuns()
    }
  }, 5000)
}

function stopRunsPolling() {
  if (runsTimer) {
    clearInterval(runsTimer)
    runsTimer = null
  }
}

onMounted(async () => {
  try {
    const resp = await getSystemProxy()
    if (resp.data.proxy) defaultProxies = resp.data.proxy
  } catch {}
  loadSchedules()
  loadRuns().then(() => startRunsPolling())
})

onUnmounted(() => {
  stopRunsPolling()
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.page-title {
  font-size: 18px;
  font-weight: 600;
}

.mono-input :deep(textarea) {
  font-family: var(--font-mono);
  font-size: 12px;
}

.session-link {
  color: #409eff;
  text-decoration: none;
}

.session-link:hover {
  text-decoration: underline;
}
</style>
