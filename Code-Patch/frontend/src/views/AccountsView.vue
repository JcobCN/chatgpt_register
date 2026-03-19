<template>
  <div>
    <div class="page-header">
      <span class="page-title">账号查询</span>
      <div class="header-actions">
        <el-button :icon="Download" :disabled="total === 0" @click="exportResults">导出账号</el-button>
        <el-button type="success" @click="importVisible = true">
          <el-icon><Upload /></el-icon>
          导入账号
        </el-button>
      </div>
    </div>

    <!-- Search + Check tabs -->
    <el-card class="panel-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="搜索筛选" name="search">
          <div class="filter-row">
            <div class="filter-item flex-1">
              <div class="field-label">关键词（Email / Account ID）</div>
              <el-input
                v-model="searchForm.keyword"
                placeholder="输入邮箱或 Account ID..."
                clearable
                @keyup.enter="doSearch"
                @clear="doSearch"
              >
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
            </div>
            <div class="filter-item">
              <div class="field-label">状态</div>
              <el-select v-model="searchForm.status" placeholder="全部" clearable style="width:110px;">
                <el-option label="成功" value="success" />
                <el-option label="失败" value="failed" />
              </el-select>
            </div>
            <div class="filter-item">
              <div class="field-label">存活</div>
              <el-select v-model="searchForm.alive" placeholder="全部" clearable style="width:110px;">
                <el-option label="存活" value="alive" />
                <el-option label="已死" value="dead" />
                <el-option label="未检测" value="unchecked" />
                <el-option label="检测异常" value="error" />
              </el-select>
            </div>
            <div class="filter-item" style="align-self:flex-end;">
              <el-button type="primary" :icon="Search" :loading="loading" @click="doSearch">查询</el-button>
            </div>
          </div>
          <el-alert
            v-if="searchForm.status === 'success'"
            title="当前仅显示注册成功的账号"
            type="info"
            :closable="false"
            show-icon
            style="margin-top: 10px;"
          />
        </el-tab-pane>

        <el-tab-pane name="check">
          <template #label>
            检测存活
            <el-badge
              v-if="selectedIds.length > 0"
              :value="selectedIds.length"
              style="margin-left: 4px;"
            />
          </template>
          <div class="filter-row">
            <div class="filter-item flex-1">
              <div class="field-label">检测代理池（每行一个）</div>
              <el-input
                v-model="checkForm.proxies"
                type="textarea"
                :rows="2"
                placeholder="http://127.0.0.1:10809"
                class="mono-input"
              />
            </div>
            <div class="filter-item">
              <div class="field-label">检测数量</div>
              <el-input-number v-model="checkForm.limit" :min="0" :max="1000000" style="width:130px;" />
              <div class="field-hint">0 = 全部</div>
            </div>
            <div class="filter-item">
              <div class="field-label">检测范围</div>
              <el-select v-model="checkForm.filter" style="width:150px;">
                <el-option value="all" label="全部成功账号" />
                <el-option value="alive" label="仅存活账号" />
                <el-option value="unchecked" label="仅未检测账号" />
              </el-select>
            </div>
            <div class="filter-item">
              <div class="field-label">并发数</div>
              <el-input-number v-model="checkForm.concurrency" :min="1" :max="1000" style="width:110px;" />
            </div>
            <div class="filter-item" style="align-self:flex-end; display:flex; flex-direction:column; gap:6px;">
              <el-checkbox v-model="checkForm.autoClean">检测后清理失效账号</el-checkbox>
              <el-button
                type="warning"
                :disabled="selectedIds.length === 0 || checking"
                :loading="checking"
                @click="startCheck(selectedIds)"
              >
                检测选中 {{ selectedIds.length > 0 ? `(${selectedIds.length})` : '' }}
              </el-button>
              <el-button
                type="danger"
                :disabled="checkTotal === 0 || checking"
                :loading="checking"
                @click="startCheckAll"
              >
                检测 {{ checkForm.limit > 0 ? checkForm.limit : '全部' }} ({{ checkTotal }})
              </el-button>
            </div>
          </div>

          <div v-if="checkProgress.total > 0" style="margin-top: 12px;">
            <div class="progress-stats">
              <span style="color:#67c23a;">存活 {{ checkProgress.alive }}</span>
              <span style="color:#f56c6c;">已死 {{ checkProgress.dead }}</span>
              <span style="color:#e6a23c;">异常 {{ checkProgress.error }}</span>
              <span>共 {{ checkProgress.total }}</span>
            </div>
            <el-progress :percentage="checkPct" :status="checking ? '' : 'success'" :stroke-width="8" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- Results table -->
    <el-card>
      <div class="table-meta">
        共 <b>{{ total }}</b> 条记录
        <el-text v-if="selectedIds.length > 0" type="primary" style="margin-left:12px;">
          已选 {{ selectedIds.length }} 条
        </el-text>
      </div>

      <el-table
        ref="tableRef"
        :data="rows"
        v-loading="loading"
        border
        size="small"
        style="width:100%;"
        @row-click="openDetail"
        @selection-change="onSelectionChange"
        :row-style="{ cursor: 'pointer' }"
      >
        <el-table-column type="selection" width="42" @click.stop />
        <el-table-column prop="id" label="ID" width="65" />
        <el-table-column prop="session_id" label="批次" width="60" align="center" />
        <el-table-column prop="email" label="Email" min-width="200" show-overflow-tooltip />
        <el-table-column prop="account_id" label="Account ID" min-width="150" show-overflow-tooltip />
        <el-table-column label="存活" width="85" align="center">
          <template #default="{ row }">
            <el-tag :type="aliveTagType(row.alive)" size="small">{{ aliveLabel(row.alive) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="套餐" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.plan_type" :type="planTagType(row.plan_type)" size="small">{{ row.plan_type }}</el-tag>
            <span v-else style="color:#c0c4cc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="配额" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.usage_json" style="font-size:12px;">{{ usageSummary(row.usage_json) }}</span>
            <span v-else style="color:#c0c4cc;">—</span>
          </template>
        </el-table-column>
        <el-table-column label="检测时间" width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ formatTime(row.checked_at) }}</template>
        </el-table-column>
        <el-table-column prop="expired" label="过期时间" width="170" show-overflow-tooltip />
        <el-table-column label="注册状态" width="75" align="center">
          <template #default="{ row }">
            <el-tag :type="row.error ? 'danger' : 'success'" size="small">
              {{ row.error ? '失败' : '成功' }}
            </el-tag>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="暂无账号数据">
            <el-button @click="doSearch">刷新</el-button>
          </el-empty>
        </template>
      </el-table>

      <div style="display:flex; justify-content:flex-end; margin-top:12px;">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          @change="doSearch"
        />
      </div>
    </el-card>

    <!-- Detail drawer -->
    <el-drawer
      v-model="drawerVisible"
      title="账号详情"
      direction="rtl"
      size="520px"
      :destroy-on-close="true"
    >
      <el-skeleton :loading="!detail" :rows="8" animated>
        <template #default>
          <div v-if="detail" style="font-size:13px;">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="ID">{{ detail.id }}</el-descriptions-item>
              <el-descriptions-item label="批次">{{ detail.session_id }}</el-descriptions-item>
              <el-descriptions-item label="注册状态">
                <el-tag :type="detail.error ? 'danger' : 'success'" size="small">
                  {{ detail.error ? '失败' : '成功' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="存活状态">
                <el-tag :type="aliveTagType(detail.alive)" size="small">{{ aliveLabel(detail.alive) }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="上次自动刷新">{{ formatTime(detail.last_auto_refresh) }}</el-descriptions-item>
              <el-descriptions-item label="检测时间">{{ formatTime(detail.checked_at) }}</el-descriptions-item>
              <el-descriptions-item label="Email">{{ detail.email || '—' }}</el-descriptions-item>
              <el-descriptions-item label="Account ID">{{ detail.account_id || '—' }}</el-descriptions-item>
              <el-descriptions-item label="过期时间">{{ detail.expired || '—' }}</el-descriptions-item>
              <el-descriptions-item label="套餐类型">
                <el-tag v-if="detail.plan_type" :type="planTagType(detail.plan_type)" size="small">{{ detail.plan_type }}</el-tag>
                <span v-else>—</span>
              </el-descriptions-item>
              <el-descriptions-item v-if="parsedUsage" label="Rate Limit">
                <span :style="{ color: parsedUsage.rate_limit?.limit_reached ? '#f56c6c' : '#67c23a' }">
                  {{ parsedUsage.rate_limit?.allowed ? '可用' : '不可用' }}
                </span>
                <span v-if="parsedUsage.rate_limit?.primary_window" style="margin-left:8px; color:#909399;">
                  已用 {{ parsedUsage.rate_limit.primary_window.used_percent }}%
                </span>
              </el-descriptions-item>
              <el-descriptions-item v-if="parsedUsage?.promo" label="推广">
                {{ parsedUsage.promo.message || parsedUsage.promo.campaign_id }}
              </el-descriptions-item>
              <el-descriptions-item label="代理">{{ detail.proxy_used || '—' }}</el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
              <el-descriptions-item v-if="detail.error" label="错误信息">
                <span style="color:#f56c6c; word-break:break-all;">{{ detail.error }}</span>
              </el-descriptions-item>
            </el-descriptions>

            <template v-if="!detail.error">
              <div class="token-section-title">Token 信息</div>
              <div v-for="field in tokenFields" :key="field.key" class="token-block-wrap">
                <div class="token-block-header">
                  <span class="token-label">{{ field.label }}</span>
                  <el-button size="small" text @click="copyText(detail[field.key])">
                    <el-icon><CopyDocument /></el-icon>
                    复制
                  </el-button>
                </div>
                <div class="token-block">{{ detail[field.key] || '—' }}</div>
              </div>
            </template>
          </div>
        </template>
      </el-skeleton>
    </el-drawer>

    <!-- Import dialog -->
    <el-dialog v-model="importVisible" title="导入账号" width="520px" :close-on-click-modal="!importing">
      <el-alert
        title="每行一个 refresh_token，或完整 JSON 对象（需含 refresh_token 字段）。导入时自动验证存活并开启自动刷新保活。"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 10px;"
      />
      <el-upload
        :before-upload="handleCsvUpload"
        :show-file-list="false"
        accept=".csv,.txt"
        :disabled="importing"
        style="margin-bottom: 10px;"
      >
        <el-button :icon="Upload" :disabled="importing">选择 CSV / TXT 文件</el-button>
      </el-upload>
      <el-input
        v-model="importForm.tokens"
        type="textarea"
        :rows="8"
        placeholder="粘贴 refresh_token / JSON / CSV 内容，每行一个；或点击上方按钮上传文件"
        class="mono-input"
        :disabled="importing"
      />
      <div class="filter-row" style="margin-top:12px;">
        <div class="filter-item flex-1">
          <div class="field-label">代理（留空使用系统代理）</div>
          <el-input v-model="importForm.proxy" placeholder="http://127.0.0.1:10809" :disabled="importing" />
        </div>
        <div class="filter-item">
          <div class="field-label">并发</div>
          <el-input-number v-model="importForm.concurrency" :min="1" :max="5" style="width:100px;" :disabled="importing" />
        </div>
      </div>

      <div v-if="importProgress.total > 0" style="margin-top:16px;">
        <div class="progress-stats">
          <span style="color:#67c23a;">有效 {{ importProgress.alive }}</span>
          <span style="color:#f56c6c;">失效 {{ importProgress.dead + importProgress.error }}</span>
          <span>共 {{ importProgress.total }}</span>
        </div>
        <el-progress :percentage="importPct" :status="importing ? '' : 'success'" :stroke-width="8" />
      </div>

      <template #footer>
        <el-button @click="importVisible = false" :disabled="importing">取消</el-button>
        <el-button type="primary" :loading="importing" @click="startImport">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Download, Upload, CopyDocument } from '@element-plus/icons-vue'
import {
  getAccounts, getAccount, exportAccountsUrl, getSystemProxy,
  startCheckSession, importAccounts, deleteDeadAccounts,
  openImportWS,
} from '../api/index.js'
import { formatTime, aliveTagType, aliveLabel } from '../utils/format.js'
import { useCheckState } from '../composables/useCheckState.js'

const { checking, checkProgress, checkPct, startCheck: globalStartCheck, stopCheck } = useCheckState()

const searchForm = reactive({ keyword: '', status: 'success', alive: '' })
const rows = ref([])
const total = ref(0)
const checkTotal = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const activeTab = ref('search')

const drawerVisible = ref(false)
const detail = ref(null)
const tableRef = ref(null)

const selectedIds = ref([])
const checkForm = reactive({ proxies: '', concurrency: 5, limit: 0, filter: 'all', autoClean: true })

const importVisible = ref(false)
const importing = ref(false)
const importForm = reactive({ tokens: '', proxy: '', concurrency: 3 })
const importProgress = reactive({ total: 0, done: 0, alive: 0, dead: 0, error: 0 })

let importWs = null

const importPct = computed(() => {
  if (!importProgress.total) return 0
  return Math.round((importProgress.done / importProgress.total) * 100)
})

const tokenFields = [
  { key: 'refresh_token', label: 'Refresh Token' },
  { key: 'access_token', label: 'Access Token' },
  { key: 'id_token', label: 'ID Token' },
]

function planTagType(plan) {
  const map = { team: 'success', plus: 'warning', pro: '', enterprise: 'danger', free: 'info' }
  return map[plan] || 'info'
}

function usageSummary(usageJsonStr) {
  if (!usageJsonStr) return ''
  try {
    const data = JSON.parse(usageJsonStr)
    const rl = data.rate_limit
    if (!rl) return ''
    const pct = rl.primary_window?.used_percent ?? '?'
    return rl.limit_reached ? `${pct}% 限制` : `${pct}%`
  } catch { return '' }
}

const parsedUsage = computed(() => {
  if (!detail.value?.usage_json) return null
  try { return JSON.parse(detail.value.usage_json) } catch { return null }
})

async function doSearch() {
  loading.value = true
  try {
    const resp = await getAccounts({
      search: searchForm.keyword || undefined,
      status: searchForm.status || undefined,
      alive: searchForm.alive || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = resp.data.items
    total.value = resp.data.total
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

function onSelectionChange(selection) {
  selectedIds.value = selection.map((r) => r.id)
}

async function loadCheckTotal() {
  try {
    let aliveFilter = undefined
    if (checkForm.filter === 'alive') aliveFilter = 'alive'
    else if (checkForm.filter === 'unchecked') aliveFilter = 'unchecked'
    const resp = await getAccounts({ status: 'success', alive: aliveFilter, page: 1, page_size: 1 })
    checkTotal.value = resp.data.total
  } catch { checkTotal.value = 0 }
}

watch(() => checkForm.filter, () => loadCheckTotal(), { immediate: true })

async function startCheckAll() {
  loading.value = true
  try {
    const ids = []
    const limit = checkForm.limit > 0 ? checkForm.limit : Infinity
    // 根据检测范围设置 alive 过滤
    let aliveFilter = undefined
    if (checkForm.filter === 'alive') aliveFilter = 'alive'
    else if (checkForm.filter === 'unchecked') aliveFilter = 'unchecked'
    let p = 1
    while (ids.length < limit) {
      const resp = await getAccounts({
        status: 'success',
        alive: aliveFilter,
        page: p,
        page_size: 200,
      })
      for (const r of resp.data.items) {
        ids.push(r.id)
        if (ids.length >= limit) break
      }
      if (ids.length >= resp.data.total) break
      p++
    }
    await startCheck(ids)
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

async function startCheck(ids) {
  if (!checkForm.proxies.trim()) {
    ElMessage.warning('请填写检测代理')
    return
  }

  const rowMap = {}
  rows.value.forEach((r) => { rowMap[r.id] = r })

  try {
    const resp = await startCheckSession({
      account_ids: ids,
      proxies: checkForm.proxies,
      concurrency: checkForm.concurrency,
    })
    globalStartCheck(resp.data.check_id, ids.length, {
      onResult(msg) {
        if (rowMap[msg.account_id]) rowMap[msg.account_id].alive = msg.alive
      },
      onDone(msg) {
        ElMessage.success(`检测完成：存活 ${msg.alive}，已死 ${msg.dead}，异常 ${msg.error}`)
        if (checkForm.autoClean && msg.dead > 0) {
          deleteDeadAccounts().then((resp) => {
            ElMessage.success(`已清理 ${resp.data.deleted} 个失效账号`)
            doSearch()
            loadCheckTotal()
          }).catch(() => { doSearch(); loadCheckTotal() })
        } else {
          doSearch()
          loadCheckTotal()
        }
      },
    })
  } catch (err) {
    ElMessage.error(err.message)
  }
}

function handleCsvUpload(file) {
  const reader = new FileReader()
  reader.onload = (e) => {
    importForm.tokens = e.target.result
    ElMessage.success(`已加载文件：${file.name}`)
  }
  reader.readAsText(file)
  return false // 阻止 el-upload 自动上传
}

async function startImport() {
  const lines = importForm.tokens.split('\n').filter(l => l.trim())
  if (!lines.length) { ElMessage.warning('请输入至少一个 token'); return }

  importing.value = true
  importProgress.total = lines.length
  importProgress.done = 0
  importProgress.alive = 0
  importProgress.dead = 0
  importProgress.error = 0

  try {
    const resp = await importAccounts({
      tokens: importForm.tokens,
      proxy: importForm.proxy,
      concurrency: importForm.concurrency,
    })
    importWs = openImportWS(resp.data.import_id, {
      onResult(msg) {
        importProgress.done++
        if (msg.alive === 'alive') importProgress.alive++
        else if (msg.alive === 'dead') importProgress.dead++
        else importProgress.error++
      },
      onDone(msg) {
        importing.value = false
        importWs?.close()
        ElMessage.success(`导入完成：有效 ${msg.alive}，失效 ${msg.dead + msg.error}`)
        doSearch()
      },
      onError() {
        ElMessage.error('连接异常')
        importing.value = false
      },
    })
  } catch (err) {
    ElMessage.error(err.message)
    importing.value = false
  }
}

async function openDetail(row) {
  drawerVisible.value = true
  detail.value = null
  try {
    const resp = await getAccount(row.id)
    detail.value = resp.data
  } catch (err) {
    ElMessage.error(err.message)
    drawerVisible.value = false
  }
}

function exportResults() {
  window.open(exportAccountsUrl({
    search: searchForm.keyword || undefined,
    status: searchForm.status || undefined,
    alive: searchForm.alive || undefined,
  }))
}

async function copyText(text) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

onMounted(async () => {
  try {
    const resp = await getSystemProxy()
    if (resp.data.proxy) {
      checkForm.proxies = resp.data.proxy
      importForm.proxy = resp.data.proxy
    }
  } catch {}
  doSearch()
})

onUnmounted(() => {
  importWs?.close()
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

.header-actions {
  display: flex;
  gap: 8px;
}

.panel-card {
  margin-bottom: 12px;
}

.filter-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: flex-start;
}

.filter-item {
  display: flex;
  flex-direction: column;
}

.flex-1 { flex: 1; min-width: 200px; }

.field-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.field-hint {
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 2px;
}

.mono-input :deep(textarea),
.mono-input :deep(input) {
  font-family: var(--font-mono);
  font-size: 12px;
}

.progress-stats {
  font-size: 12px;
  color: #606266;
  margin-bottom: 6px;
  display: flex;
  gap: 12px;
}

.table-meta {
  margin-bottom: 8px;
  color: #606266;
  font-size: 13px;
}

.token-section-title {
  margin-top: 20px;
  margin-bottom: 10px;
  font-weight: 600;
  color: #303133;
}

.token-block-wrap {
  margin-bottom: 14px;
}

.token-block-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.token-label {
  color: #606266;
  font-size: 12px;
  font-weight: 500;
}

.token-block {
  background: var(--color-log-bg);
  color: #c9d1d9;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  word-break: break-all;
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}
</style>
