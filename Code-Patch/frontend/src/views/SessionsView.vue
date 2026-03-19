<template>
  <div>
    <!-- Page header -->
    <div class="page-header">
      <div>
        <span class="page-title">注册记录</span>
        <el-text type="info" size="small" style="margin-left: 8px;">共 {{ sessions.length }} 条记录</el-text>
      </div>
      <el-button :icon="Refresh" circle @click="loadSessions" :loading="loadingSessions" />
    </div>

    <!-- Filter bar -->
    <el-card class="filter-card">
      <el-row :gutter="12" align="middle">
        <el-col :span="10">
          <el-input
            v-model="filterKeyword"
            placeholder="搜索 ID 或日期..."
            :prefix-icon="Search"
            clearable
            size="small"
          />
        </el-col>
        <el-col :span="8">
          <el-select v-model="filterStatus" placeholder="全部状态" clearable size="small" style="width: 100%;">
            <el-option label="全部状态" value="" />
            <el-option label="运行中" value="running" />
            <el-option label="已暂停" value="paused" />
            <el-option label="导入中" value="importing" />
            <el-option label="已完成" value="done" />
          </el-select>
        </el-col>
      </el-row>
    </el-card>

    <!-- Sessions table -->
    <el-card>
      <el-table
        :data="filteredSessions"
        v-loading="loadingSessions"
        row-key="id"
        stripe
        @expand-change="onExpand"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div style="padding: 12px 24px;">
              <el-table
                :data="accountsMap[row.id] || []"
                v-loading="loadingAccounts[row.id]"
                size="small"
                :max-height="300"
              >
                <el-table-column prop="id" label="ID" width="60" />
                <el-table-column prop="email" label="Email" min-width="180" />
                <el-table-column prop="account_id" label="Account ID" min-width="160" show-overflow-tooltip />
                <el-table-column label="过期时间" width="180">
                  <template #default="{ row: acct }">{{ formatTime(acct.expired) }}</template>
                </el-table-column>
                <el-table-column prop="exit_ip" label="出口 IP" min-width="140" show-overflow-tooltip />
                <el-table-column prop="proxy_used" label="代理" min-width="140" show-overflow-tooltip />
                <el-table-column label="存活" width="90">
                  <template #default="{ row: acct }">
                    <el-tag :type="aliveTagType(acct.alive)" size="small">{{ aliveLabel(acct.alive) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="注册状态" width="80">
                  <template #default="{ row: acct }">
                    <el-tag :type="acct.error ? 'danger' : 'success'" size="small">
                      {{ acct.error ? '失败' : '成功' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="error" label="错误" min-width="160" show-overflow-tooltip />
              </el-table>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="proxy_count" label="代理数" width="70" align="center" />
        <el-table-column prop="requested" label="目标" width="60" align="center" />
        <el-table-column prop="concurrency" label="并发" width="60" align="center" />
        <el-table-column label="IP 统计" width="140" align="center">
          <template #default="{ row }">
            <span v-if="row.unique_ips > 0">
              <span class="ip-unique">{{ row.unique_ips }}</span> 个
              <span v-if="row.reused_ips > 0" class="ip-reused">（重复 {{ row.reused_ips }}）</span>
            </span>
            <span v-else style="color: #c0c4cc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="成功" width="60" align="center">
          <template #default="{ row }">
            <span class="count-success">{{ row.success }}</span>
          </template>
        </el-table-column>
        <el-table-column label="失败" width="60" align="center">
          <template #default="{ row }">
            <span class="count-failed">{{ row.failed }}</span>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="100" align="center">
          <template #default="{ row }">
            <span v-if="row.requested > 0">{{ row.success }} / {{ row.requested }}</span>
            <span v-else style="color: #c0c4cc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="成功率" width="80" align="center">
          <template #default="{ row }">
            <span v-if="row.success + row.failed > 0" :style="{ color: successRateColor(row) }">
              {{ Math.round((row.success / (row.success + row.failed)) * 100) }}%
            </span>
            <span v-else style="color: #c0c4cc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag
              :type="statusTagType(row.status)"
              size="small"
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <div style="display:flex; gap:4px; justify-content:center;">
              <el-button
                v-if="row.status === 'running'"
                type="warning"
                size="small"
                @click.stop="doPause(row.id)"
              >
                暂停
              </el-button>
              <el-button
                v-if="row.status === 'paused'"
                type="success"
                size="small"
                @click.stop="doResume(row.id)"
              >
                继续
              </el-button>
              <el-button
                type="primary"
                size="small"
                :icon="Download"
                @click.stop="exportSession(row.id)"
                :disabled="row.success === 0"
              >
                导出
              </el-button>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="暂无注册记录">
            <el-button @click="loadSessions">刷新</el-button>
          </el-empty>
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { Refresh, Search, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getSessions, getAccounts, exportSessionUrl, pauseSession, resumeSession } from '../api/index.js'
import { formatTime, aliveTagType, aliveLabel } from '../utils/format.js'

const sessions = ref([])
const loadingSessions = ref(false)
const accountsMap = reactive({})
const loadingAccounts = reactive({})
const filterKeyword = ref('')
const filterStatus = ref('')

const filteredSessions = computed(() => {
  return sessions.value.filter(s => {
    const matchesStatus = !filterStatus.value || s.status === filterStatus.value
    const matchesKeyword = !filterKeyword.value ||
      String(s.id).includes(filterKeyword.value) ||
      (s.created_at && s.created_at.includes(filterKeyword.value))
    return matchesStatus && matchesKeyword
  })
})

function statusTagType(s) {
  if (s === 'done') return 'success'
  if (s === 'paused') return 'info'
  if (s === 'importing') return 'primary'
  return 'warning'
}

function statusLabel(s) {
  const map = { done: '已完成', paused: '已暂停', importing: '导入中', running: '运行中' }
  return map[s] || s
}

function successRateColor(row) {
  const total = row.success + row.failed
  if (total === 0) return '#c0c4cc'
  const rate = row.success / total
  if (rate >= 0.8) return '#67c23a'
  if (rate >= 0.5) return '#e6a23c'
  return '#f56c6c'
}

let pollTimer = null

async function loadSessions() {
  loadingSessions.value = true
  try {
    const resp = await getSessions()
    sessions.value = resp.data
  } finally {
    loadingSessions.value = false
  }
}

async function onExpand(row, expandedRows) {
  const isExpanded = expandedRows.some((r) => r.id === row.id)
  if (!isExpanded || accountsMap[row.id]) return

  loadingAccounts[row.id] = true
  try {
    const resp = await getAccounts({ session_id: row.id, page_size: 200 })
    accountsMap[row.id] = resp.data.items
  } finally {
    loadingAccounts[row.id] = false
  }
}

function exportSession(id) {
  window.open(exportSessionUrl(id))
}

async function doPause(id) {
  try {
    await pauseSession(id)
    ElMessage.info('已暂停')
  } catch (err) {
    ElMessage.warning(err.message)
  }
  await loadSessions()
}

async function doResume(id) {
  try {
    await resumeSession(id)
    ElMessage.success('已恢复')
  } catch (err) {
    ElMessage.warning(err.message)
  }
  await loadSessions()
}

function startPolling() {
  pollTimer = setInterval(async () => {
    if (document.hidden) return
    const hasRunning = sessions.value.some((s) => s.status === 'running' || s.status === 'importing' || s.status === 'paused')
    if (hasRunning) await loadSessions()
  }, 3000)
}

onMounted(() => {
  loadSessions()
  startPolling()
})

onUnmounted(() => {
  clearInterval(pollTimer)
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

.filter-card {
  margin-bottom: 12px;
}

.filter-card :deep(.el-card__body) {
  padding: 12px 16px;
}

.count-success {
  color: #67c23a;
  font-weight: 600;
}

.count-failed {
  color: #f56c6c;
  font-weight: 600;
}

.ip-unique {
  color: #409eff;
  font-weight: 600;
}

.ip-reused {
  color: #e6a23c;
  font-size: 12px;
}
</style>
