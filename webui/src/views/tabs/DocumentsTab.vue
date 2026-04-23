<template>
  <div class="docs-workbench page-grid">
    <section class="hero view-card">
      <div class="hero__copy">
        <div class="eyebrow">Ingest Control Room</div>
        <h2 class="hero__title">文档入库、任务追踪和后端日志集中在一个工作台里</h2>
        <p class="hero__desc">
          基础入库会优先完成，保证向量检索和关键词检索可用；图谱构建在后端异步推进，失败后也可以保留中间状态继续重试。
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
          <span class="hero-stat__label">失败任务</span>
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
              <div class="panel__sub">图谱失败后可保留基础检索、块级进度和融合阶段检查点</div>
            </div>
            <div class="panel__actions">
              <el-button type="success" @click="openUpload">上传文件</el-button>
              <el-button type="primary" @click="openCreate">录入文本</el-button>
              <el-button :loading="refreshing" @click="refreshAll">刷新</el-button>
            </div>
          </div>
        </template>

        <el-table
          :data="docs"
          v-loading="docsLoading"
          row-key="doc_id"
          class="shell-table"
          empty-text="当前分组还没有文档"
        >
          <el-table-column prop="doc_name" label="文档" min-width="220">
            <template #default="{ row }">
              <div class="doc-cell">
                <div class="doc-cell__name">{{ row.doc_name || row.doc_id }}</div>
                <div class="doc-cell__meta mono">doc_id: {{ row.doc_id }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="doc_time" label="时间" width="200" />
          <el-table-column label="录入状态" width="180">
            <template #default="{ row }">
              <div class="task-pill">
                <span class="status-dot" :class="`is-${docStageTone(row)}`" />
                <div>
                  <div>{{ docStageLabel(row) }}</div>
                  <div class="task-pill__sub">{{ docStageHint(row) }}</div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="图谱进度" min-width="300">
            <template #default="{ row }">
              <div class="graph-progress">
                <div class="graph-progress__summary">
                  <span class="summary-pill is-success">完成 {{ graphProgress(row).completed_chunks }}</span>
                  <span class="summary-pill is-danger">失败 {{ graphProgress(row).failed_chunks }}</span>
                  <span class="summary-pill is-warning">处理中 {{ graphProgress(row).processing_chunks }}</span>
                  <span class="summary-pill is-info">总数 {{ graphProgress(row).total_chunks }}</span>
                </div>
                <div class="graph-progress__pipeline">
                  <div class="graph-progress__stage">{{ graphStageLabel(row) }}</div>
                  <div class="graph-progress__hint">{{ graphStageHint(row) }}</div>
                  <div v-if="graphTrace(row).steps?.length" class="graph-progress__trace">
                    <span class="summary-pill" :class="`is-${chunkTone(graphTrace(row).summary?.status || 'pending')}`">
                      {{ chunkStatusLabel(graphTrace(row).summary?.status || 'pending') }}
                    </span>
                    <span class="graph-progress__trace-text">
                      Trace · {{ graphTrace(row).summary?.current_step_name || '暂无步骤' }}
                    </span>
                  </div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="最近任务" width="220">
            <template #default="{ row }">
              <div v-if="taskMap[row.doc_id]" class="task-pill">
                <span class="status-dot" :class="`is-${taskTone(taskMap[row.doc_id].status)}`" />
                <div>
                  <div>{{ taskLabel(taskMap[row.doc_id]) }}</div>
                  <div class="task-pill__sub">{{ taskMap[row.doc_id].updated_at }}</div>
                </div>
              </div>
              <span v-else class="task-empty">暂无任务</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="300">
            <template #default="{ row }">
              <div class="table-actions">
                <el-button size="small" @click="openReingest(row)">重建</el-button>
                <el-button size="small" @click="openChunks(row)">文本块</el-button>
                <el-button
                  v-if="canRetryGraph(row)"
                  size="small"
                  type="warning"
                  :loading="retryingDocId === row.doc_id"
                  @click="retryGraph(row)"
                >
                  重试图谱
                </el-button>
                <el-button size="small" @click="focusDocLogs(row.doc_id)">日志</el-button>
                <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
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
              <div class="panel__sub">自动轮询中，状态会推进到 completed 或 failed</div>
            </div>
            <div class="panel__actions">
              <el-switch v-model="autoRefresh" active-text="自动刷新" inactive-text="手动" />
            </div>
          </div>
        </template>

        <div class="task-board" v-loading="tasksLoading">
          <div class="task-board__toolbar">
            <el-button @click="clearFinishedTasks" :disabled="!tasks.length">清理已结束</el-button>
            <el-switch v-model="autoRefresh" active-text="自动刷新" inactive-text="手动" />
          </div>
          <div v-if="!tasks.length" class="task-board__empty">当前还没有入库任务</div>
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
            <div class="task-card__actions">
              <el-button
                size="small"
                text
                type="danger"
                :disabled="['pending', 'running'].includes(task.status)"
                @click.stop="deleteTask(task)"
              >
                删除任务
              </el-button>
            </div>
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
              <div class="panel__sub">支持按 group_id、doc_id、task_id 和关键字过滤</div>
            </div>
            <div class="panel__actions">
              <el-button :loading="logsLoading" @click="loadLogs">刷新日志</el-button>
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
          <el-input v-model="form.doc_name" placeholder="例如 report.txt" class="glass-input" />
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
              <div class="upload-dropzone__sub">支持当前后端允许的文档、Office、表格和图片格式</div>
            </div>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDlg = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="upload">提交任务</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="chunksDrawer" :title="chunksTitle" size="55%" append-to-body>
      <div class="chunks-panel" v-loading="chunksLoading">
        <div class="chunks-panel__meta" v-if="chunksDoc">
          <span>doc_id: {{ chunksDoc.doc_id }}</span>
          <span>chunk 数: {{ filteredChunks.length }}/{{ chunks.length }}</span>
          <span>状态: {{ docStageLabel(chunksDoc) }}</span>
          <span>
            进度: {{ graphProgress(chunksDoc).completed_chunks }}/{{ graphProgress(chunksDoc).total_chunks }}
          </span>
        </div>
        <div class="chunk-filter-bar">
          <el-input
            v-model="chunkFilter.query"
            clearable
            placeholder="搜索 chunk_id、文本、错误、告警、抽取结果"
            class="glass-input chunk-filter-bar__search"
          />
          <el-select v-model="chunkFilter.status" class="glass-select chunk-filter-bar__select">
            <el-option label="全部状态" value="all" />
            <el-option label="失败" value="failed" />
            <el-option label="处理中" value="running" />
            <el-option label="已完成" value="completed" />
            <el-option label="待处理" value="pending" />
          </el-select>
          <el-switch v-model="chunkFilter.issueOnly" active-text="仅看问题块" inactive-text="全部块" />
          <el-button @click="resetChunkFilter">重置筛选</el-button>
        </div>
        <div class="chunk-filter-summary">
          <span class="summary-pill is-danger">问题块 {{ problematicChunkCount }}</span>
          <span class="summary-pill is-warning">过滤后 {{ filteredChunks.length }}</span>
          <span v-if="chunkFilter.query" class="summary-pill is-info">关键词 {{ chunkFilter.query }}</span>
        </div>
        <div v-if="graphTrace(chunksDoc).steps?.length" class="trace-panel">
          <div class="trace-panel__head">
            <div class="trace-panel__title">文档级 Trace</div>
            <div class="trace-panel__summary">
              <span class="summary-pill" :class="`is-${chunkTone(graphTrace(chunksDoc).summary?.status || 'pending')}`">
                {{ chunkStatusLabel(graphTrace(chunksDoc).summary?.status || 'pending') }}
              </span>
              <span>{{ graphTrace(chunksDoc).summary?.current_step_name || '暂无步骤' }}</span>
            </div>
          </div>
          <div class="trace-step-list">
            <div v-for="step in graphTrace(chunksDoc).steps" :key="step.step_id" class="trace-step-card">
              <div class="trace-step-card__head">
                <strong>{{ step.title || step.step_name }}</strong>
                <span class="summary-pill" :class="`is-${chunkTone(step.status)}`">{{ chunkStatusLabel(step.status) }}</span>
              </div>
              <div class="trace-step-card__meta">
                <span>{{ step.kind }}</span>
                <span v-if="step.updated_at">{{ step.updated_at }}</span>
                <span v-if="step.latency_ms">耗时 {{ Math.round(step.latency_ms) }} ms</span>
              </div>
              <div v-if="step.error?.message" class="trace-step-card__error">{{ step.error.message }}</div>
            </div>
          </div>
        </div>
        <div v-if="!chunks.length && !chunksLoading" class="chunks-panel__empty">当前文档还没有可展示的文本块</div>
        <div v-else-if="!filteredChunks.length" class="chunks-panel__empty">没有符合当前筛选条件的文本块</div>
        <div v-else class="chunk-list">
          <article v-for="chunk in filteredChunks" :key="chunk.chunk_id" class="chunk-card" :class="{ 'is-problem': chunkHasIssue(chunk) }">
            <header class="chunk-card__head">
              <div>
                <div class="chunk-card__title">Chunk {{ chunk.index + 1 }}</div>
                <div class="chunk-card__meta mono">{{ chunk.chunk_id }}</div>
              </div>
              <div class="chunk-card__status-wrap">
                <span class="summary-pill" :class="`is-${chunkTone(chunk.status)}`">{{ chunkStatusLabel(chunk.status) }}</span>
                <span v-if="chunk.updated_at" class="chunk-card__meta">{{ chunk.updated_at }}</span>
              </div>
            </header>
            <div class="chunk-card__toolbar">
              <div class="chunk-card__stats">
                <span class="summary-pill is-info">实体 {{ chunkEntityCount(chunk) }}</span>
                <span class="summary-pill is-info">关系 {{ chunkRelationCount(chunk) }}</span>
                <span class="summary-pill" :class="chunk.parse_errors?.length ? 'is-warning' : 'is-success'">
                  告警 {{ chunk.parse_errors?.length || 0 }}
                </span>
                <span v-if="chunkHasIssue(chunk)" class="summary-pill is-danger">问题块</span>
              </div>
              <el-button
                size="small"
                type="warning"
                plain
                :loading="retryingChunkId === chunk.chunk_id"
                @click="retryChunk(chunk)"
              >
                重试该块
              </el-button>
            </div>
            <div v-if="chunk.error" class="chunk-card__error">{{ chunk.error }}</div>
            <div v-if="chunk.trace_step" class="chunk-trace">
              <div class="chunk-trace__head">
                <span class="chunk-trace__title">{{ chunk.trace_step.title || chunk.trace_step.step_name }}</span>
                <span class="summary-pill" :class="`is-${chunkTone(chunk.trace_step.status)}`">
                  {{ chunkStatusLabel(chunk.trace_step.status) }}
                </span>
              </div>
              <div class="chunk-trace__meta">
                <span>{{ chunk.trace_step.kind }}</span>
                <span v-if="chunk.trace_step.updated_at">{{ chunk.trace_step.updated_at }}</span>
                <span v-if="chunk.trace_step.error?.message">{{ chunk.trace_step.error.message }}</span>
              </div>
            </div>
            <div class="chunk-card__section">
              <div class="chunk-card__section-title">原始文本</div>
              <pre class="chunk-card__text">{{ chunk.text }}</pre>
            </div>
            <div v-if="chunk.resolved_text" class="chunk-card__section">
              <div class="chunk-card__section-title">块内指代消解结果</div>
              <pre class="chunk-card__text">{{ chunk.resolved_text }}</pre>
            </div>
            <div v-if="chunk.entity_relation_raw" class="chunk-card__section">
              <div class="chunk-card__section-title">抽取原始输出</div>
              <pre class="chunk-card__text">{{ chunk.entity_relation_raw }}</pre>
            </div>
            <div class="chunk-card__split">
              <div class="chunk-card__section">
                <div class="chunk-card__section-title">解析出的实体</div>
                <pre v-if="chunk.parsed_entities?.length" class="chunk-card__json">{{ prettyJson(chunk.parsed_entities) }}</pre>
                <div v-else class="chunk-card__empty">当前块没有解析出实体</div>
              </div>
              <div class="chunk-card__section">
                <div class="chunk-card__section-title">解析出的关系</div>
                <pre v-if="chunk.parsed_relations?.length" class="chunk-card__json">{{ prettyJson(chunk.parsed_relations) }}</pre>
                <div v-else class="chunk-card__empty">当前块没有解析出关系</div>
              </div>
            </div>
            <div v-if="chunk.parse_errors?.length" class="chunk-card__section">
              <div class="chunk-card__section-title">解析告警</div>
              <ul class="chunk-card__errors">
                <li v-for="(item, idx) in chunk.parse_errors" :key="`${chunk.chunk_id}-err-${idx}`">{{ item }}</li>
              </ul>
            </div>
          </article>
        </div>
      </div>
    </el-drawer>
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
const retryingDocId = ref('')
const retryingChunkId = ref('')

const docs = ref([])
const tasks = ref([])
const selectedTaskId = ref('')
const autoRefresh = ref(true)
let timer = null

const dlg = ref(false)
const uploadDlg = ref(false)
const chunksDrawer = ref(false)
const chunksLoading = ref(false)
const chunks = ref([])
const chunksDoc = ref(null)
const chunkFilter = reactive({
  query: '',
  status: 'all',
  issueOnly: false,
})

const form = reactive({
  doc_id: '',
  doc_name: '',
  doc_time: '',
  text: '',
})

const uploadForm = reactive({
  doc_id: '',
  doc_time: null,
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

const chunksTitle = computed(() => {
  const row = chunksDoc.value
  if (!row) return '文本块'
  return `${row.doc_name || row.doc_id} · 文本块`
})

const problematicChunkCount = computed(() => chunks.value.filter((chunk) => chunkHasIssue(chunk)).length)

const filteredChunks = computed(() => {
  const query = String(chunkFilter.query || '').trim().toLowerCase()
  return chunks.value.filter((chunk) => {
    if (chunkFilter.issueOnly && !chunkHasIssue(chunk)) return false
    if (chunkFilter.status !== 'all' && normalizeChunkStatus(chunk?.status) !== chunkFilter.status) return false
    if (!query) return true
    return buildChunkSearchText(chunk).includes(query)
  })
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
  if (logQuery.task_id && !logState.fallback_used) return '当前 task_id 下没有匹配日志'
  if (logQuery.doc_id) return '当前 doc_id 下没有匹配日志'
  return '没有匹配到日志'
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

function readDocStage(row) {
  return String(row?.metadata?.ingest_stage || '').trim() || 'unknown'
}

function graphProgress(row) {
  return row?.graph_progress || {
    total_chunks: 0,
    completed_chunks: 0,
    failed_chunks: 0,
    processing_chunks: 0,
    pending_chunks: 0,
    latest_stage: '',
    latest_status: '',
    pipeline: {},
  }
}

function graphTrace(row) {
  return row?.graph_trace || {
    summary: {
      status: 'pending',
      current_step_name: '',
    },
    steps: [],
  }
}

function docStageLabel(row) {
  const stage = readDocStage(row)
  if (stage === 'base_completed') return '基础入库完成'
  if (stage === 'graph_processing') return '图谱构建中'
  if (stage === 'graph_completed') return '图谱构建完成'
  if (stage === 'graph_failed') return '图谱构建失败'
  if (stage === 'graph_retrying') return '图谱重试中'
  return '状态未知'
}

function docStageTone(row) {
  const stage = readDocStage(row)
  if (stage === 'graph_completed') return 'success'
  if (stage === 'graph_failed') return 'danger'
  if (stage === 'graph_processing' || stage === 'graph_retrying') return 'warning'
  return 'info'
}

function docStageHint(row) {
  const stage = readDocStage(row)
  if (stage === 'base_completed') return '基础检索可用'
  if (stage === 'graph_processing') return '图谱任务正在运行'
  if (stage === 'graph_completed') return '图检索已可用'
  if (stage === 'graph_failed') return '已保留中间状态，可继续重试'
  if (stage === 'graph_retrying') return '正在基于已有中间状态继续运行'
  return '等待状态同步'
}

function canRetryGraph(row) {
  const stage = readDocStage(row)
  return stage === 'graph_failed' || stage === 'base_completed' || stage === 'graph_retrying'
}

function graphStageText(stage) {
  if (stage === 'fusion') return '文档内融合'
  if (stage === 'doc_graph_assets') return '文档级图资产'
  if (stage === 'entity_alignment') return '实体对齐'
  if (stage === 'relation_alignment') return '关系对齐'
  if (stage === 'mentions') return 'Mention 生成'
  if (stage === 'graph_index') return '图索引构建'
  if (stage === 'save_graph_assets') return '图谱落库'
  return '未开始'
}

function graphStageLabel(row) {
  return graphTrace(row).summary?.current_step_name || graphStageText(graphProgress(row).latest_stage)
}

function graphStageHint(row) {
  const progress = graphProgress(row)
  const trace = graphTrace(row)
  if (trace.summary?.current_step_name) {
    return `${trace.summary?.status || 'pending'} · ${trace.summary.current_step_name}`
  }
  if (!progress.latest_stage) return '暂无图谱阶段检查点'
  const current = progress.pipeline?.[progress.latest_stage]
  const alignmentFallbackCount = Number(progress.entity_alignment_fallback_count || 0)
  if (alignmentFallbackCount > 0) {
    return `${progress.latest_status || 'unknown'} · 实体对齐阶段有 ${alignmentFallbackCount} 次回退`
  }
  if (current?.error) return `${progress.latest_status} · ${current.error}`
  return `${progress.latest_status || 'unknown'}`
}

function chunkTone(status) {
  const normalized = normalizeChunkStatus(status)
  if (normalized === 'completed') return 'success'
  if (normalized === 'failed') return 'danger'
  if (normalized === 'running') return 'warning'
  return 'info'
}

function chunkStatusLabel(status) {
  const normalized = normalizeChunkStatus(status)
  if (normalized === 'completed') return '已完成'
  if (normalized === 'failed') return '失败'
  if (normalized === 'running') return '处理中'
  return '待处理'
}

function normalizeChunkStatus(status) {
  const value = String(status || '').trim().toLowerCase()
  if (value === 'processing') return 'running'
  if (value === 'done' || value === 'success') return 'completed'
  if (value === 'error') return 'failed'
  return value || 'pending'
}

function chunkHasIssue(chunk) {
  if (!chunk) return false
  if (normalizeChunkStatus(chunk.status) === 'failed') return true
  if (chunk.error) return true
  if (Array.isArray(chunk.parse_errors) && chunk.parse_errors.length > 0) return true
  if (normalizeChunkStatus(chunk?.trace_step?.status) === 'failed') return true
  if (chunk?.trace_step?.error?.message) return true
  return false
}

function buildChunkSearchText(chunk) {
  return [
    chunk?.chunk_id,
    chunk?.text,
    chunk?.resolved_text,
    chunk?.entity_relation_raw,
    chunk?.error,
    chunk?.trace_step?.title,
    chunk?.trace_step?.step_name,
    chunk?.trace_step?.error?.message,
    Array.isArray(chunk?.parse_errors) ? chunk.parse_errors.join('\n') : '',
    Array.isArray(chunk?.parsed_entities) ? JSON.stringify(chunk.parsed_entities) : '',
    Array.isArray(chunk?.parsed_relations) ? JSON.stringify(chunk.parsed_relations) : '',
  ]
    .filter(Boolean)
    .join('\n')
    .toLowerCase()
}

function chunkEntityCount(chunk) {
  return Array.isArray(chunk?.parsed_entities) ? chunk.parsed_entities.length : 0
}

function chunkRelationCount(chunk) {
  return Array.isArray(chunk?.parsed_relations) ? chunk.parsed_relations.length : 0
}

function prettyJson(value) {
  try {
    return JSON.stringify(value || [], null, 2)
  } catch {
    return String(value || '')
  }
}

function resetChunkFilter() {
  chunkFilter.query = ''
  chunkFilter.status = 'all'
  chunkFilter.issueOnly = false
}

async function openChunks(row) {
  chunksDoc.value = row
  chunksDrawer.value = true
  chunksLoading.value = true
  chunks.value = []
  resetChunkFilter()
  try {
    const res = await api.get(`/documents/${encodeURIComponent(row.doc_id)}/chunks`, {
      params: { group_id: props.groupId, limit: 5000 },
    })
    chunks.value = Array.isArray(res.data) ? res.data : []
  } finally {
    chunksLoading.value = false
  }
}

async function refreshChunks() {
  if (!chunksDoc.value) return
  chunksLoading.value = true
  try {
    const res = await api.get(`/documents/${encodeURIComponent(chunksDoc.value.doc_id)}/chunks`, {
      params: { group_id: props.groupId, limit: 5000 },
    })
    chunks.value = Array.isArray(res.data) ? res.data : []
  } finally {
    chunksLoading.value = false
  }
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
    if (selectedTaskId.value && !tasks.value.some((task) => task.task_id === selectedTaskId.value)) {
      selectedTaskId.value = ''
      if (logQuery.task_id) logQuery.task_id = ''
    }
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

async function retryGraph(row) {
  retryingDocId.value = row.doc_id
  try {
    const res = await api.post('/ingest/retry-graph', {
      group_id: props.groupId,
      doc_id: row.doc_id,
    })
    handleTaskAccepted(res.data, row.doc_id)
  } finally {
    retryingDocId.value = ''
  }
}

async function retryChunk(chunk) {
  if (!chunksDoc.value) return
  retryingChunkId.value = chunk.chunk_id
  try {
    const res = await api.post(
      `/documents/${encodeURIComponent(chunksDoc.value.doc_id)}/chunks/${encodeURIComponent(chunk.chunk_id)}/retry`,
      null,
      { params: { group_id: props.groupId } },
    )
    const rebuildTask = res.data?.graph_rebuild_task
    if (rebuildTask?.task_id) {
      ElMessage.success(`块重试成功，已自动触发图谱续跑：${rebuildTask.task_id}`)
    } else {
      ElMessage.success('块重试已完成')
    }
    await Promise.all([loadDocs(), loadTasks(), refreshChunks()])
    await loadLogs()
  } finally {
    retryingChunkId.value = ''
  }
}

async function deleteTask(task) {
  await ElMessageBox.confirm(`确认删除任务 ${task.task_id} ？`, '删除确认', { type: 'warning' })
  await api.delete(`/ingest-tasks/${encodeURIComponent(task.task_id)}`)
  if (selectedTaskId.value === task.task_id) selectedTaskId.value = ''
  if (logQuery.task_id === task.task_id) logQuery.task_id = ''
  ElMessage.success('任务记录已删除')
  await loadTasks()
  await loadLogs()
}

async function clearFinishedTasks() {
  await ElMessageBox.confirm('确认清理当前分组下已结束的任务记录？运行中的任务不会被清理。', '清理确认', { type: 'warning' })
  const res = await api.post('/ingest-tasks/clear', {
    group_id: props.groupId,
    statuses: ['completed', 'failed'],
  })
  const deleted = Number(res.data?.deleted || 0)
  ElMessage.success(`已清理 ${deleted} 条任务记录`)
  if (selectedTaskId.value && !tasks.value.some((task) => task.task_id === selectedTaskId.value)) {
    selectedTaskId.value = ''
    logQuery.task_id = ''
  }
  await loadTasks()
  await loadLogs()
}

async function remove(row) {
  await ElMessageBox.confirm(`确认删除 doc_id=${row.doc_id} ?`, '删除确认', { type: 'warning' })
  await api.delete(`/documents/${encodeURIComponent(row.doc_id)}`, { params: { group_id: props.groupId } })
  ElMessage.success('已删除')
  if (logQuery.doc_id === row.doc_id) logQuery.doc_id = ''
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

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  flex: 0 0 auto;
  box-shadow: 0 0 0 4px rgba(0, 0, 0, 0.04);
}

.task-pill__sub,
.task-empty,
.task-card__meta,
.task-card__time {
  font-size: 12px;
  color: #768894;
}

.graph-progress {
  display: grid;
  gap: 8px;
}

.graph-progress__summary {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.graph-progress__pipeline {
  display: grid;
  gap: 4px;
}

.graph-progress__stage {
  font-size: 13px;
  font-weight: 700;
  color: #183246;
}

.graph-progress__hint {
  font-size: 12px;
  color: #6f808c;
  word-break: break-word;
}

.graph-progress__trace {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.graph-progress__trace-text {
  font-size: 12px;
  color: #516977;
}

.summary-pill,
.task-card__status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.task-board {
  display: grid;
  gap: 10px;
  max-height: 560px;
  overflow: auto;
}

.task-board__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
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

.task-card__title {
  font-weight: 700;
  color: #102231;
}

.task-card__message {
  font-size: 13px;
  color: #425966;
  line-height: 1.5;
}

.task-card__actions {
  display: flex;
  justify-content: flex-end;
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

.chunks-panel {
  display: grid;
  gap: 14px;
}

.trace-panel {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-radius: 18px;
  border: 1px solid #d8e4eb;
  background: linear-gradient(180deg, #fbfdff 0%, #f5f9fc 100%);
}

.trace-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.trace-panel__title {
  font-weight: 700;
  color: #173246;
}

.trace-panel__summary {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #647987;
}

.trace-step-list {
  display: grid;
  gap: 8px;
}

.trace-step-card {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #dbe5ec;
}

.trace-step-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.trace-step-card__meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #70828e;
}

.trace-step-card__error {
  font-size: 12px;
  color: #9c2323;
}

.chunks-panel__meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #6f808c;
}

.chunk-filter-bar {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) 180px auto auto;
  gap: 10px;
  align-items: center;
}

.chunk-filter-bar__search,
.chunk-filter-bar__select {
  width: 100%;
}

.chunk-filter-summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chunks-panel__empty {
  padding: 24px;
  border-radius: 16px;
  background: #f4f7f9;
  color: #738491;
  text-align: center;
}

.chunk-list {
  display: grid;
  gap: 12px;
  max-height: calc(100vh - 180px);
  overflow: auto;
  padding-right: 6px;
}

.chunk-card {
  border: 1px solid #d9e4ea;
  border-radius: 18px;
  background: #ffffff;
  padding: 14px;
  display: grid;
  gap: 10px;
}

.chunk-card.is-problem {
  border-color: #f0b0b0;
  box-shadow: 0 8px 18px rgba(156, 35, 35, 0.06);
}

.chunk-card__head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}

.chunk-card__status-wrap {
  display: grid;
  gap: 6px;
  justify-items: end;
}

.chunk-card__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.chunk-card__stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chunk-card__title {
  font-weight: 700;
  color: #102231;
}

.chunk-card__meta {
  font-size: 12px;
  color: #768894;
}

.chunk-card__text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.65;
  font-size: 13px;
  color: #314754;
  background: #f8fbfd;
  border-radius: 14px;
  padding: 12px;
}

.chunk-card__section {
  display: grid;
  gap: 8px;
}

.chunk-card__section-title {
  font-size: 12px;
  font-weight: 700;
  color: #48606f;
}

.chunk-card__split {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.chunk-card__json {
  margin: 0;
  min-height: 64px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font-size: 12px;
  color: #244050;
  background: #f6fafc;
  border: 1px solid #d8e4eb;
  border-radius: 14px;
  padding: 12px;
}

.chunk-card__empty {
  padding: 12px;
  border-radius: 12px;
  background: #f7fafb;
  color: #738491;
  font-size: 12px;
}

.chunk-card__errors {
  margin: 0;
  padding-left: 18px;
  color: #8f4a00;
  font-size: 12px;
  line-height: 1.7;
}

.chunk-card__error {
  font-size: 12px;
  line-height: 1.5;
  color: #9c2323;
  background: #fff1f1;
  border: 1px solid #ffd7d7;
  border-radius: 12px;
  padding: 10px 12px;
  word-break: break-word;
}

.chunk-trace {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 14px;
  background: #f6fafc;
  border: 1px solid #d8e4eb;
}

.chunk-trace__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.chunk-trace__title {
  font-size: 12px;
  font-weight: 700;
  color: #1c3b50;
}

.chunk-trace__meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #6d7f8b;
}

@media (max-width: 960px) {
  .chunk-filter-bar,
  .chunk-card__split {
    grid-template-columns: 1fr;
  }
}

.is-success {
  background: #d6f5df;
  color: #0f6a3b;
}

.status-dot.is-success {
  background: #1f9d55;
}

.is-warning {
  background: #fff0c7;
  color: #8a5a00;
}

.status-dot.is-warning {
  background: #d99100;
}

.is-danger {
  background: #ffd7d7;
  color: #9c2323;
}

.status-dot.is-danger {
  background: #cc3d3d;
}

.is-info {
  background: #dbeaf4;
  color: #31556f;
}

.status-dot.is-info {
  background: #5d7f95;
}

@media (max-width: 1100px) {
  .hero,
  .workbench-grid,
  .log-toolbar {
    grid-template-columns: 1fr;
  }
}
</style>
