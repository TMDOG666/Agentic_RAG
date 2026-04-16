<template>
  <div class="docs-workbench page-grid">
    <section class="hero view-card">
      <div class="hero__copy">
        <div class="eyebrow">Ingest Control Room</div>
        <h2 class="hero__title">文档录入、任务追踪和后端日志放在同一个工作台里。</h2>
        <p class="hero__desc">
          提交文本或文件后，界面会持续刷新任务状态与日志。日志区域会优先按文档过滤；如果带上 `task_id`
          没命中，也会自动回退一次，避免看起来像“没有日志”。
        </p>
      </div>
      <div class="hero__stats">
        <div class="hero-stat">
          <span class="hero-stat__label">文档数</span>
          <strong class="hero-stat__value">{{ docs.length }}</strong>
        </div>
        <div class="hero-stat">
          <span class="hero-stat__label">运行中</span>
          <strong class="hero-stat__value">{{ runningTasks }}</strong>
        </div>
        <div class="hero-stat">
          <span class="hero-stat__label">失败数</span>
          <strong class="hero-stat__value">{{ failedTasks }}</strong>
        </div>
      </div>
    </section>

    <section class="workbench-grid">
      <el-card shadow="never" class="panel panel--documents">
        <template #header>
          <div class="panel__header">
            <div>
              <div class="panel__title">文档资产</div>
              <div class="panel__sub">基础文档会立刻保存，图谱与融合在后端异步完成。</div>
            </div>
            <div class="panel__actions">
              <el-button @click="openUpload" type="success">上传文件</el-button>
              <el-button @click="openCreate" type="primary">录入文本</el-button>
              <el-button @click="refreshAll" :loading="refreshing">刷新</el-button>
            </div>
          </div>
        </template>

        <el-table :data="docs" v-loading="docsLoading" row-key="doc_id" class="shell-table" empty-text="当前分组还没有文档">
          <el-table-column prop="doc_name" label="文档" min-width="260">
            <template #default="scope">
              <div class="doc-cell">
                <div class="doc-cell__name">{{ scope.row.doc_name || scope.row.doc_id }}</div>
                <div class="doc-cell__meta mono">doc_id: {{ scope.row.doc_id }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="doc_time" label="时间" width="220" />
          <el-table-column label="最近任务" width="230">
            <template #default="scope">
              <div v-if="taskMap[scope.row.doc_id]" class="task-pill">
                <span class="status-dot" :class="`is-${taskTone(taskMap[scope.row.doc_id].status)}`" />
                <div>
                  <div>{{ taskLabel(taskMap[scope.row.doc_id]) }}</div>
                  <div class="task-pill__sub">{{ taskMap[scope.row.doc_id].updated_at }}</div>
                </div>
              </div>
              <span v-else class="task-empty">暂无任务</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220">
            <template #default="scope">
              <div class="table-actions">
                <el-button size="small" @click="openReingest(scope.row)">重建</el-button>
                <el-button size="small" @click="focusDocLogs(scope.row.doc_id)">日志</el-button>
                <el-button size="small" type="danger" @click="remove(scope.row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="panel panel--tasks">
        <template #header>
          <div class="panel__header panel__header--stack">
            <div>
              <div class="panel__title">入库任务队列</div>
              <div class="panel__sub">自动轮询中，状态会推进到 `completed` 或 `failed`。</div>
            </div>
            <div class="panel__actions">
              <el-switch v-model="autoRefresh" active-text="自动刷新" inactive-text="手动" />
            </div>
          </div>
        </template>

        <div class="task-board" v-loading="tasksLoading">
          <div v-if="!tasks.length" class="task-board__empty">当前还没有入库任务。</div>
          <button
            v-for="task in tasks"
            :key="task.task_id"
            class="task-card"
            :class="{ 'is-active': selectedTaskId === task.task_id }"
            @click="selectTask(task)"
          >
            <div class="task-card__head">
              <span class="task-card__status" :class="`is-${taskTone(task.status)}`">{{ task.status }}</span>
              <span class="task-card__time">{{ task.updated_at }}</span>
            </div>
            <div class="task-card__title">{{ task.doc_name || task.doc_id }}</div>
            <div class="task-card__meta">{{ task.stage }} · {{ task.doc_id }}</div>
            <div class="task-card__message">{{ task.message }}</div>
          </button>
        </div>
      </el-card>
    </section>

    <section class="log-grid">
      <el-card shadow="never" class="panel panel--logs">
        <template #header>
          <div class="panel__header">
            <div>
              <div class="panel__title">后端日志</div>
              <div class="panel__sub">
                支持按 `group_id / doc_id / task_id / contains` 过滤。部分日志行没有 `task_id`，因此前端会自动做一次回退查询。
              </div>
            </div>
            <div class="panel__actions">
              <el-button @click="loadLogs" :loading="logsLoading">刷新日志</el-button>
            </div>
          </div>
        </template>

        <div class="log-toolbar">
          <el-input v-model="logQuery.doc_id" placeholder="doc_id" clearable class="glass-input" />
          <el-input v-model="logQuery.task_id" placeholder="task_id" clearable class="glass-input" />
          <el-input v-model="logQuery.contains" placeholder="关键字过滤" clearable class="glass-input" />
          <el-select v-model="logQuery.lines" class="glass-select" style="width: 120px">
            <el-option :value="100" label="100 行" />
            <el-option :value="200" label="200 行" />
            <el-option :value="400" label="400 行" />
          </el-select>
        </div>

        <div class="log-meta">
          <span>日志文件: {{ logState.file_path || '未知' }}</span>
          <span v-if="selectedTaskId">当前任务: {{ selectedTaskId }}</span>
          <span v-if="logState.fallback_used">已自动忽略 task_id 过滤</span>
        </div>

        <div class="log-console" v-loading="logsLoading">
          <div v-if="!logState.lines.length" class="log-console__empty">{{ logEmptyText }}</div>
          <pre v-else>{{ logState.lines.join('\n') }}</pre>
        </div>
      </el-card>
    </section>

    <el-dialog v-model="dlg" title="录入文本" width="760px" append-to-body align-center>
      <el-form label-width="90px">
        <el-form-item label="doc_id">
          <el-input v-model="form.doc_id" placeholder="可选：留空新建；填写则按同一 doc_id 重建" class="glass-input" />
        </el-form-item>
        <el-form-item label="doc_name">
          <el-input v-model="form.doc_name" placeholder="例如：report.txt" class="glass-input" />
        </el-form-item>
        <el-form-item label="doc_time">
          <el-input v-model="form.doc_time" placeholder="ISO8601，例如 2026-03-05T07:12:34Z" class="glass-input" />
        </el-form-item>
        <el-form-item label="text">
          <el-input v-model="form.text" type="textarea" :rows="10" placeholder="输入要入库的正文" class="glass-input" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">提交任务</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="uploadDlg" title="上传文件并入库" width="760px" append-to-body align-center>
      <el-form label-width="90px">
        <el-form-item label="文档 ID">
          <el-input v-model="uploadForm.doc_id" placeholder="可选：留空新建；填写则按同一文档重建" class="glass-input" />
        </el-form-item>
        <el-form-item label="文档时间">
          <el-date-picker v-model="uploadForm.doc_time" type="datetime" placeholder="请选择时间" style="width: 100%" />
        </el-form-item>
        <el-form-item label="标准化">
          <el-switch v-model="uploadForm.standardize" />
        </el-form-item>
        <el-form-item label="文件">
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :on-change="onUploadChange"
            :on-remove="onUploadRemove"
            :show-file-list="true"
            style="width: 100%"
          >
            <div class="upload-dropzone">
              <div class="upload-dropzone__title">拖拽文件到这里</div>
              <div class="upload-dropzone__sub">支持当前后端配置允许的文档、Office、表格和图片格式</div>
            </div>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDlg = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="upload">提交任务</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../lib/api'

const props = defineProps({
  groupId: { type: String, required: true },
})

const docsLoading = ref(false)
const tasksLoading = ref(false)
const logsLoading = ref(false)
const refreshing = ref(false)
const saving = ref(false)
const uploading = ref(false)

const docs = ref([])
const tasks = ref([])
const selectedTaskId = ref('')
const autoRefresh = ref(true)
let timer = null

const dlg = ref(false)
const uploadDlg = ref(false)

const form = reactive({
  doc_id: '',
  doc_name: '',
  doc_time: '',
  text: '',
})

const uploadForm = reactive({
  doc_id: '',
  doc_time: null,
  standardize: true,
  file: null,
  filename: '',
})

const logQuery = reactive({
  doc_id: '',
  task_id: '',
  contains: '',
  lines: 200,
})

const logState = reactive({
  file_path: '',
  lines: [],
  fallback_used: false,
})

const taskMap = computed(() => {
  const out = {}
  for (const task of tasks.value) {
    if (!out[task.doc_id]) out[task.doc_id] = task
  }
  return out
})

const runningTasks = computed(() => tasks.value.filter((x) => ['pending', 'running'].includes(x.status)).length)
const failedTasks = computed(() => tasks.value.filter((x) => x.status === 'failed').length)
const logEmptyText = computed(() => {
  if (logQuery.task_id && !logState.fallback_used) return '当前 task_id 下没有匹配日志。'
  if (logQuery.doc_id) return '当前 doc_id 下没有匹配日志。'
  return '没有匹配到日志。'
})

function taskTone(status) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function taskLabel(task) {
  return `${task.status} · ${task.stage}`
}

async function loadDocs() {
  docsLoading.value = true
  try {
    const res = await api.get(`/groups/${encodeURIComponent(props.groupId)}/documents`, { params: { limit: 200 } })
    docs.value = Array.isArray(res.data) ? res.data : []
  } finally {
    docsLoading.value = false
  }
}

async function loadTasks() {
  tasksLoading.value = true
  try {
    const res = await api.get('/ingest-tasks', {
      params: { group_id: props.groupId, limit: 100 },
    })
    tasks.value = Array.isArray(res.data) ? res.data : []
    if (!selectedTaskId.value && tasks.value.length) {
      selectTask(tasks.value[0], { silent: true })
    }
  } finally {
    tasksLoading.value = false
  }
}

async function tailLogs(params) {
  const res = await api.get('/logs/tail', { params })
  return {
    file_path: String(res.data?.file_path || ''),
    lines: Array.isArray(res.data?.lines) ? res.data.lines : [],
  }
}

async function loadLogs() {
  logsLoading.value = true
  try {
    const baseParams = {
      group_id: props.groupId,
      doc_id: (logQuery.doc_id || '').trim() || undefined,
      task_id: (logQuery.task_id || '').trim() || undefined,
      contains: (logQuery.contains || '').trim() || undefined,
      lines: logQuery.lines,
    }
    const primary = await tailLogs(baseParams)
    logState.file_path = primary.file_path
    logState.lines = primary.lines
    logState.fallback_used = false

    if (!primary.lines.length && baseParams.task_id) {
      const fallback = await tailLogs({ ...baseParams, task_id: undefined })
      if (fallback.lines.length) {
        logState.file_path = fallback.file_path
        logState.lines = fallback.lines
        logState.fallback_used = true
      }
    }
  } finally {
    logsLoading.value = false
  }
}

async function refreshAll() {
  refreshing.value = true
  try {
    await Promise.all([loadDocs(), loadTasks(), loadLogs()])
  } finally {
    refreshing.value = false
  }
}

function openCreate() {
  form.doc_id = ''
  form.doc_name = ''
  form.doc_time = ''
  form.text = ''
  dlg.value = true
}

function openReingest(row) {
  form.doc_id = row.doc_id
  form.doc_name = row.doc_name
  form.doc_time = row.doc_time
  form.text = ''
  dlg.value = true
}

function openUpload() {
  uploadForm.doc_id = ''
  uploadForm.doc_time = null
  uploadForm.standardize = true
  uploadForm.file = null
  uploadForm.filename = ''
  uploadDlg.value = true
}

function onUploadChange(uploadFile) {
  const raw = uploadFile?.raw
  uploadForm.file = raw || null
  uploadForm.filename = raw?.name || uploadFile?.name || ''
}

function onUploadRemove() {
  uploadForm.file = null
  uploadForm.filename = ''
}

function selectTask(task, options = {}) {
  selectedTaskId.value = task.task_id
  logQuery.task_id = task.task_id
  logQuery.doc_id = task.doc_id
  if (!options.silent) loadLogs()
}

function focusDocLogs(docId) {
  logQuery.doc_id = String(docId || '')
  logQuery.task_id = ''
  selectedTaskId.value = ''
  loadLogs()
}

function handleTaskAccepted(resData, fallbackDocId = '') {
  const taskId = String(resData?.task_id || '').trim()
  const docId = String(resData?.doc_id || fallbackDocId || '').trim()
  ElMessage.success(`任务已提交：doc_id=${docId}${taskId ? `，task_id=${taskId}` : ''}`)
  if (taskId) {
    selectedTaskId.value = taskId
    logQuery.task_id = taskId
  }
  if (docId) {
    logQuery.doc_id = docId
  }
  refreshAll()
}

async function save() {
  const payload = {
    group_id: props.groupId,
    doc_id: (form.doc_id || '').trim() || null,
    doc_name: (form.doc_name || '').trim(),
    doc_time: (form.doc_time || '').trim(),
    text: form.text || '',
  }
  if (!payload.doc_name || !payload.doc_time || !payload.text) {
    ElMessage.warning('doc_name / doc_time / text 不能为空')
    return
  }

  saving.value = true
  try {
    const res = await api.post('/ingest/text', payload)
    dlg.value = false
    handleTaskAccepted(res.data, payload.doc_id || '')
  } finally {
    saving.value = false
  }
}

async function upload() {
  if (!uploadForm.file) {
    ElMessage.warning('请选择文件')
    return
  }
  if (!uploadForm.doc_time) {
    ElMessage.warning('文档时间不能为空')
    return
  }

  let docTimeIso = ''
  try {
    docTimeIso = new Date(uploadForm.doc_time).toISOString()
  } catch {
    docTimeIso = ''
  }
  if (!docTimeIso) {
    ElMessage.warning('文档时间格式不合法')
    return
  }

  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', uploadForm.file)
    const params = {
      group_id: props.groupId,
      doc_time: docTimeIso,
      doc_id: String(uploadForm.doc_id || '').trim() || undefined,
      standardize: Boolean(uploadForm.standardize),
    }
    const res = await api.post('/ingest/upload', fd, {
      params,
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    uploadDlg.value = false
    handleTaskAccepted(res.data, params.doc_id || '')
  } finally {
    uploading.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确认删除 doc_id=${row.doc_id} ?`, '删除确认', { type: 'warning' })
  await api.delete(`/documents/${encodeURIComponent(row.doc_id)}`, { params: { group_id: props.groupId } })
  ElMessage.success('已删除')
  if (logQuery.doc_id === row.doc_id) {
    logQuery.doc_id = ''
  }
  await refreshAll()
}

function startPolling() {
  stopPolling()
  timer = window.setInterval(() => {
    if (!autoRefresh.value) return
    loadTasks()
    loadLogs()
    loadDocs()
  }, 5000)
}

function stopPolling() {
  if (timer) {
    window.clearInterval(timer)
    timer = null
  }
}

onMounted(async () => {
  await refreshAll()
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.docs-workbench {
  display: grid;
  gap: 16px;
}

.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(280px, 0.9fr);
  gap: 16px;
  padding: 22px;
  border-radius: 24px;
  background:
    radial-gradient(circle at top left, rgba(246, 196, 90, 0.35), transparent 28%),
    linear-gradient(135deg, #13293d 0%, #1f4e5f 52%, #f3efe6 52%, #f6f1e8 100%);
  color: #0b1720;
  overflow: hidden;
}

.hero__copy {
  display: grid;
  gap: 10px;
  color: #f4f7fb;
}

.hero__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  max-width: 760px;
}

.hero__desc {
  margin: 0;
  max-width: 720px;
  font-size: 14px;
  line-height: 1.7;
  color: rgba(244, 247, 251, 0.84);
}

.hero__stats {
  display: grid;
  gap: 12px;
  align-content: center;
}

.hero-stat {
  padding: 16px 18px;
  border-radius: 18px;
  background: rgba(255, 250, 240, 0.72);
  backdrop-filter: blur(8px);
}

.hero-stat__label {
  display: block;
  font-size: 12px;
  color: #5f5a4f;
}

.hero-stat__value {
  display: block;
  margin-top: 6px;
  font-size: 30px;
  line-height: 1;
  color: #1a2530;
}

.workbench-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.85fr);
  gap: 16px;
}

.log-grid {
  display: grid;
}

.panel {
  border-radius: 22px;
  border: 1px solid #d7e1e8;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcfd 100%);
}

.panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.panel__header--stack {
  align-items: center;
}

.panel__title {
  font-size: 16px;
  font-weight: 700;
  color: #102231;
}

.panel__sub {
  margin-top: 4px;
  font-size: 12px;
  color: #6e7f8b;
}

.panel__actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.doc-cell {
  display: grid;
  gap: 4px;
}

.doc-cell__name {
  font-weight: 600;
  color: #11293b;
}

.doc-cell__meta {
  font-size: 12px;
  color: #70828e;
}

.table-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.task-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.task-pill__sub,
.task-empty,
.task-card__meta,
.task-card__time {
  font-size: 12px;
  color: #768894;
}

.task-board {
  display: grid;
  gap: 10px;
  max-height: 560px;
  overflow: auto;
}

.task-board__empty {
  padding: 24px;
  border-radius: 16px;
  background: #f4f7f9;
  color: #738491;
  text-align: center;
}

.task-card {
  display: grid;
  gap: 8px;
  width: 100%;
  padding: 14px;
  border: 1px solid #d9e4ea;
  border-radius: 18px;
  text-align: left;
  background: #ffffff;
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}

.task-card:hover,
.task-card.is-active {
  transform: translateY(-1px);
  border-color: #86a3b7;
  box-shadow: 0 10px 24px rgba(18, 42, 57, 0.08);
}

.task-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.task-card__status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: #eef3f6;
}

.task-card__title {
  font-weight: 700;
  color: #102231;
}

.task-card__message {
  font-size: 13px;
  color: #425966;
  line-height: 1.5;
}

.log-toolbar {
  display: grid;
  grid-template-columns: 1fr 1fr 1.2fr 120px;
  gap: 10px;
  margin-bottom: 12px;
}

.log-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  font-size: 12px;
  color: #6f808c;
  flex-wrap: wrap;
}

.log-console {
  min-height: 360px;
  max-height: 520px;
  overflow: auto;
  padding: 14px;
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(9, 19, 28, 0.98), rgba(11, 27, 39, 0.98)),
    repeating-linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.04) 28px, transparent 28px, transparent 56px);
  color: #d8f4e7;
}

.log-console pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.55;
}

.log-console__empty {
  color: rgba(216, 244, 231, 0.7);
}

.upload-dropzone {
  padding: 12px 0;
}

.upload-dropzone__title {
  font-weight: 700;
  color: #183246;
}

.upload-dropzone__sub {
  margin-top: 6px;
  font-size: 12px;
  color: #72838f;
}

.is-success {
  background: #d6f5df;
  color: #0f6a3b;
}

.is-warning {
  background: #fff0c7;
  color: #8a5a00;
}

.is-danger {
  background: #ffd7d7;
  color: #9c2323;
}

.is-info {
  background: #dbeaf4;
  color: #31556f;
}

@media (max-width: 1100px) {
  .hero,
  .workbench-grid,
  .log-toolbar {
    grid-template-columns: 1fr;
  }
}
</style>
