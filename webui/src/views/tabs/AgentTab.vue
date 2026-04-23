<template>
  <div class="agent-workbench">
    <el-card shadow="never" class="view-card session-panel">
      <template #header>
        <div class="session-panel__header">
          <div>
            <div class="section-title">会话历史</div>
            <div class="section-subtitle">当前历史只保存在浏览器本地，后续可独立替换为后端持久化模块。</div>
          </div>
          <el-button type="primary" class="brand-button" @click="startNewSession">新建会话</el-button>
        </div>
      </template>

      <div class="scope-chip">
        <span class="scope-chip__label">当前范围</span>
        <strong class="scope-chip__value">{{ scopeLabel }}</strong>
      </div>

      <div v-if="!sessions.length" class="empty-state">当前范围还没有历史会话。</div>
      <div v-else class="session-list">
        <button
          v-for="session in sessions"
          :key="session.id"
          class="session-item"
          :class="{ 'is-active': session.id === activeSessionId }"
          @click="selectSession(session.id)"
        >
          <div class="session-item__head">
            <div class="session-item__title">{{ session.title }}</div>
            <el-button link type="danger" @click.stop="removeSession(session.id)">删除</el-button>
          </div>
          <div class="session-item__meta">{{ formatSessionMeta(session) }}</div>
          <div class="session-item__stats">
            <span>{{ Math.max(0, (session.messages || []).length - 1) }} 条消息</span>
            <span>{{ Array.isArray(session.runs) ? session.runs.length : 0 }} 次运行</span>
          </div>
        </button>
      </div>
    </el-card>

    <el-card shadow="never" class="view-card chat-panel">
      <template #header>
        <div class="agent-header">
          <div>
            <div class="section-title">Agent 对话工作台</div>
            <div class="section-subtitle">左侧保留对话流，右侧切换为真正的 trace 时间线视图。</div>
          </div>
          <div class="agent-header__actions">
            <el-select v-model="docId" clearable placeholder="可选：绑定 doc_id" class="glass-select agent-doc-select">
              <el-option v-for="d in docs" :key="d.doc_id" :label="`${d.doc_name} (${d.doc_id})`" :value="d.doc_id" />
            </el-select>
            <el-button class="ghost-button" :loading="docsLoading" @click="loadDocs">刷新文档</el-button>
          </div>
        </div>
      </template>

      <div class="chat-shell">
        <section ref="chatWindowEl" class="chat-window">
          <div class="chat-window__hero">
            <div>
              <div class="eyebrow">Agent Stream</div>
              <h3>流式回答 + Trace 可观测</h3>
              <p>当前会话会同步展示 Agent 推理、Tool 调用、Skill 执行、检索命中与最终回答。</p>
            </div>
            <div class="chat-window__meta">
              <div class="hero-stat">
                <span>运行状态</span>
                <strong>{{ runStatusLabel }}</strong>
              </div>
              <div class="hero-stat">
                <span>Trace 步数</span>
                <strong>{{ timelineSteps.length }}</strong>
              </div>
            </div>
          </div>

          <div v-for="(m, idx) in activeMessages" :key="`${idx}-${m.role}`" class="chat-bubble" :class="`is-${m.role}`">
            <div class="chat-bubble__top">
              <span class="chat-bubble__role">{{ messageRoleLabel(m.role) }}</span>
              <span v-if="m.streaming" class="streaming-dot">流式输出中</span>
            </div>
            <div class="chat-bubble__content markdown-body" v-html="renderMarkdown(m.content)" />
          </div>
        </section>

        <div class="chat-compose">
          <el-input
            v-model="text"
            type="textarea"
            :rows="4"
            resize="none"
            placeholder="输入问题，按 Enter 发送，Shift + Enter 换行。"
            class="glass-input compose-input"
            @keydown.enter.exact.prevent="send"
          />
          <div class="chat-compose__actions">
            <el-button class="ghost-button" @click="startNewSession">清空当前会话</el-button>
            <el-button type="primary" class="brand-button send-button" :loading="sending" @click="send">发送给 Agent</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="view-card observe-panel">
      <template #header>
        <div class="observe-header">
          <div>
            <div class="section-title">执行 Trace</div>
            <div class="section-subtitle">统一展示任务、过程、证据和 token 消耗，不再复用旧 tabs 布局。</div>
          </div>
          <el-tag :type="runStatusType" effect="light" round>{{ runStatusLabel }}</el-tag>
        </div>
      </template>

      <div class="observe-summary">
        <div class="observe-metric">
          <span>Tools / Skills</span>
          <strong>{{ currentRun.tasks.length }}</strong>
        </div>
        <div class="observe-metric">
          <span>证据条数</span>
          <strong>{{ currentRun.evidence.length }}</strong>
        </div>
        <div class="observe-metric">
          <span>事件数</span>
          <strong>{{ currentRun.events.length }}</strong>
        </div>
        <div class="observe-metric usage-metric">
          <span>Input Tokens</span>
          <strong>{{ formatTokenNumber(currentRun.usage.inputTokens) }}</strong>
        </div>
        <div class="observe-metric usage-metric">
          <span>Output Tokens</span>
          <strong>{{ formatTokenNumber(currentRun.usage.outputTokens) }}</strong>
        </div>
        <div class="observe-metric usage-metric">
          <span>Total Tokens</span>
          <strong>{{ formatTokenNumber(currentRun.usage.totalTokens) }}</strong>
        </div>
      </div>

      <div class="trace-shell">
        <div class="trace-overview">
          <div class="trace-overview__main">
            <div class="trace-overview__label">Trace</div>
            <div class="trace-overview__id mono">{{ currentRun.traceId || currentRun.id || 'pending-trace' }}</div>
            <div class="trace-overview__meta">
              <span>{{ timelineSteps.length }} steps</span>
              <span>{{ traceCompletedCount }}/{{ timelineSteps.length || 0 }} completed</span>
              <span v-if="currentRun.tracePath">path: {{ currentRun.tracePath }}</span>
            </div>
          </div>
          <div class="trace-overview__side">
            <div class="trace-overview__time">
              <span v-if="currentRun.startedAt">{{ formatTime(currentRun.startedAt) }}</span>
              <span v-if="currentRun.finishedAt">→ {{ formatTime(currentRun.finishedAt) }}</span>
            </div>
          </div>
        </div>

        <div v-if="!timelineSteps.length" class="empty-state">发送问题后，这里会按时间线展示 Agent 的推理、工具调用、检索证据和最终回答。</div>

        <div v-else class="trace-timeline">
          <article
            v-for="(step, idx) in timelineSteps"
            :key="step.step_id || `${idx}-${step.title}`"
            class="trace-card"
            :class="`is-${traceTone(step.status)}`"
          >
            <div class="trace-card__rail">
              <div class="trace-card__dot" :class="`is-${traceTone(step.status)}`">{{ idx + 1 }}</div>
              <div v-if="idx < timelineSteps.length - 1" class="trace-card__line" />
            </div>

            <div class="trace-card__body">
              <div class="trace-card__head">
                <div class="trace-card__title-wrap">
                  <div class="trace-card__eyebrow">
                    <span>{{ traceKindLabel(step.kind) }}</span>
                    <span v-if="step.event">{{ step.event }}</span>
                  </div>
                  <div class="trace-card__title">{{ step.title || step.step_name }}</div>
                  <div class="trace-card__subtitle">{{ step.step_name || step.event || 'trace step' }}</div>
                </div>
                <el-tag :type="taskStatusType(step.status)" effect="light" round>{{ taskStatusLabel(step.status) }}</el-tag>
              </div>

              <div class="trace-card__meta">
                <span v-if="step.updated_at">{{ formatTime(step.updated_at) }}</span>
                <span v-if="step.latency_ms">{{ formatLatency(step.latency_ms) }}</span>
                <span v-if="step.tokens?.totalTokens">tokens {{ formatTokenNumber(step.tokens.totalTokens) }}</span>
                <span v-if="step.tokens?.inputTokens">in {{ formatTokenNumber(step.tokens.inputTokens) }}</span>
                <span v-if="step.tokens?.outputTokens">out {{ formatTokenNumber(step.tokens.outputTokens) }}</span>
                <span v-if="step.tokens?.isEstimated">estimated</span>
              </div>

              <div v-if="tracePrimaryText(step)" class="trace-card__desc">{{ tracePrimaryText(step) }}</div>
              <div v-if="step.error?.message" class="trace-card__error">{{ step.error.message }}</div>

              <div v-if="traceEvidenceItems(step).length" class="trace-card__section">
                <div class="trace-card__section-title">Evidence</div>
                <article
                  v-for="(item, evidenceIndex) in traceEvidenceItems(step)"
                  :key="`${step.step_id}-evidence-${evidenceIndex}`"
                  class="trace-evidence-card"
                >
                  <div class="trace-evidence-card__head">
                    <el-tag size="small" effect="plain">{{ item.mode || item.type || 'evidence' }}</el-tag>
                    <span class="mono trace-evidence-card__meta">{{ item.document_name || item.doc_id || 'unknown-doc' }}</span>
                  </div>
                  <div class="trace-evidence-card__title">{{ item.entity_name || item.relation || item.chunk_id || 'evidence item' }}</div>
                  <div class="trace-evidence-card__content">{{ item.text || summarizeEvidence(item) }}</div>
                </article>
              </div>

              <div v-if="tracePayloadEntries(step).length" class="trace-card__section">
                <div class="trace-card__section-title">Payload</div>
                <div class="trace-payload-list">
                  <div
                    v-for="entry in tracePayloadEntries(step)"
                    :key="`${step.step_id}-${entry.key}`"
                    class="trace-payload-item"
                  >
                    <div class="trace-payload-item__key">{{ entry.key }}</div>
                    <pre v-if="entry.multiline" class="trace-payload-item__value">{{ entry.value }}</pre>
                    <div v-else class="trace-payload-item__value">{{ entry.value }}</div>
                  </div>
                </div>
              </div>
            </div>
          </article>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { api, postEventStream } from '../../lib/api'
import {
  normalizeTraceStatus as normalizeTraceStatusDto,
  normalizeTraceStep as normalizeTraceStepDto,
  normalizeTraceUsage as normalizeTraceUsageDto,
  sortTraceSteps,
} from '../../lib/trace'
import { createEphemeralSession, deleteSession, listSessions, upsertSession } from '../../modules/agent-chat-history'

const props = defineProps({
  groupId: { type: String, required: true },
})

const docsLoading = ref(false)
const docs = ref([])
const docId = ref('')

const text = ref('')
const sending = ref(false)
const chatWindowEl = ref(null)

const sessions = ref([])
const activeSessionId = ref('')
const activeSession = ref(createEphemeralSession({ groupId: props.groupId, docId: '' }))
const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const scopeLabel = computed(() => (
  docId.value
    ? `分组 ${props.groupId} / 文档 ${docId.value}`
    : `分组 ${props.groupId} / 全局`
))

const activeMessages = computed(() => activeSession.value?.messages || [])

const currentRun = computed(() => {
  const runs = Array.isArray(activeSession.value?.runs) ? activeSession.value.runs : []
  const run = runs[0]
  if (!run) return createRunState()

  const traceSteps = Array.isArray(run.traceSteps) ? run.traceSteps.map(normalizeTraceStep) : []
  if (traceSteps.length) {
    return {
      ...createRunState(),
      ...run,
      traceSteps,
      tasks: deriveTasksFromTrace(traceSteps),
      events: deriveEventsFromTrace(traceSteps),
      evidence: deriveEvidenceFromTrace(traceSteps),
      usage: deriveUsageFromTrace(traceSteps),
    }
  }

  return {
    ...createRunState(),
    ...run,
    usage: createUsage(run.usage || {}),
    tasks: Array.isArray(run.tasks)
      ? run.tasks.map((task) => ({ ...task, usage: createUsage(task?.usage || {}) }))
      : [],
    events: Array.isArray(run.events) ? run.events : [],
    evidence: Array.isArray(run.evidence) ? run.evidence : [],
    traceSteps: [],
  }
})

const runStatusLabel = computed(() => runStatusText(currentRun.value.status))
const runStatusType = computed(() => taskStatusType(currentRun.value.status))

const timelineSteps = computed(() => {
  if (currentRun.value.traceSteps.length) {
    return sortTraceSteps(currentRun.value.traceSteps)
  }
  return synthesizeTimelineFromRun(currentRun.value)
})

const traceCompletedCount = computed(() => (
  timelineSteps.value.filter((step) => ['done', 'completed'].includes(normalizeTraceStatus(step.status))).length
))

function createRunState() {
  return {
    id: '',
    status: 'idle',
    startedAt: '',
    finishedAt: '',
    traceId: '',
    tracePath: '',
    traceSteps: [],
    tasks: [],
    events: [],
    evidence: [],
    usage: createUsage(),
  }
}

function createRun(taskId = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`) {
  return {
    id: taskId,
    status: 'running',
    startedAt: new Date().toISOString(),
    finishedAt: '',
    traceId: '',
    tracePath: '',
    traceSteps: [],
    tasks: [],
    events: [],
    evidence: [],
    usage: createUsage(),
  }
}

function createUsage(patch = {}) {
  return {
    inputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
    isEstimated: false,
    latencyMs: 0,
    ...patch,
  }
}

function normalizeUsage(payload = {}) {
  return createUsage(normalizeTraceUsageDto(payload))
}

function normalizeTraceStatus(status) {
  return normalizeTraceStatusDto(status)
}

function normalizeTraceStep(step = {}) {
  return {
    ...normalizeTraceStepDto(step),
    source: step.source || 'agent',
    tokens: normalizeUsage(step.tokens || {}),
  }
}

function deriveTasksFromTrace(traceSteps = []) {
  return traceSteps
    .filter((step) => ['llm', 'tool', 'skill', 'retrieval', 'assistant', 'run'].includes(step.kind))
    .map((step) => ({
      id: step.step_id,
      title: step.title || step.step_name,
      kind: step.kind,
      subtitle: step.step_name || step.event,
      detail: tracePrimaryText(step),
      status:
        step.status === 'completed' ? 'done' :
        step.status === 'failed' ? 'error' :
        step.status === 'running' ? 'running' : 'pending',
      usage: normalizeUsage(step.tokens || {}),
    }))
}

function deriveEventsFromTrace(traceSteps = []) {
  return traceSteps.slice(-120).map((step) => ({
    id: step.step_id,
    title: step.title || step.step_name,
    description: tracePrimaryText(step),
    tone: traceTone(step.status),
  }))
}

function deriveEvidenceFromTrace(traceSteps = []) {
  const items = []
  for (const step of traceSteps) {
    const previews = traceEvidenceItems(step)
    if (previews.length) items.push(...previews)
  }
  return items.slice(0, 20)
}

function deriveUsageFromTrace(traceSteps = []) {
  return traceSteps.reduce((acc, step) => {
    const usage = normalizeUsage(step.tokens || {})
    acc.inputTokens += usage.inputTokens
    acc.outputTokens += usage.outputTokens
    acc.totalTokens += usage.totalTokens
    acc.latencyMs += Number(step.latency_ms || usage.latencyMs || 0) || 0
    acc.isEstimated = acc.isEstimated || usage.isEstimated
    return acc
  }, createUsage())
}

function synthesizeTimelineFromRun(run) {
  const steps = []

  ;(run.tasks || []).forEach((task, index) => {
    steps.push(normalizeTraceStep({
      step_id: `legacy-task-${index}-${task.id || index}`,
      kind: task.kind || 'task',
      event: 'legacy.task',
      title: task.title || '任务',
      step_name: task.subtitle || task.kind || 'task',
      status: task.status || 'pending',
      updated_at: run.finishedAt || run.startedAt || new Date().toISOString(),
      tokens: task.usage || {},
      payload: { detail: task.detail || '' },
    }))
  })

  ;(run.events || []).forEach((event, index) => {
    steps.push(normalizeTraceStep({
      step_id: `legacy-event-${index}-${event.id || index}`,
      kind: 'event',
      event: 'legacy.event',
      title: event.title || '事件',
      step_name: event.title || '事件',
      status: event.tone === 'danger' ? 'failed' : event.tone === 'warning' ? 'running' : 'completed',
      updated_at: run.finishedAt || run.startedAt || new Date().toISOString(),
      payload: { description: event.description || '' },
    }))
  })

  if ((run.evidence || []).length) {
    steps.push(normalizeTraceStep({
      step_id: `legacy-evidence-${run.id || 'run'}`,
      kind: 'retrieval',
      event: 'legacy.evidence',
      title: '检索证据',
      step_name: 'evidence',
      status: 'completed',
      updated_at: run.finishedAt || run.startedAt || new Date().toISOString(),
      payload: { items_preview: run.evidence.slice(0, 10) },
    }))
  }

  return steps
}

function cloneRun(run) {
  return JSON.parse(JSON.stringify(run || createRunState()))
}

function updateActiveSession(patch) {
  activeSession.value = { ...activeSession.value, ...patch }
}

function hydrateSessions() {
  sessions.value = listSessions({ groupId: props.groupId, docId: docId.value || '' })
  if (sessions.value.length) {
    if (!sessions.value.some((session) => session.id === activeSessionId.value)) {
      activeSessionId.value = sessions.value[0].id
    }
    const matched = sessions.value.find((session) => session.id === activeSessionId.value)
    if (matched) {
      activeSession.value = matched
      return
    }
  }
  activeSessionId.value = ''
  activeSession.value = createEphemeralSession({ groupId: props.groupId, docId: docId.value || '' })
}

function persistActiveSession() {
  if (!activeSession.value?.messages?.length || activeSession.value.messages.length <= 1) return
  const saved = upsertSession({
    groupId: props.groupId,
    docId: docId.value || '',
    session: activeSession.value,
  })
  activeSession.value = saved
  activeSessionId.value = saved.id
  sessions.value = listSessions({ groupId: props.groupId, docId: docId.value || '' })
}

function startNewSession() {
  activeSessionId.value = ''
  activeSession.value = createEphemeralSession({ groupId: props.groupId, docId: docId.value || '' })
  text.value = ''
  nextTick(scrollToBottom)
}

function selectSession(sessionId) {
  const matched = sessions.value.find((session) => session.id === sessionId)
  if (!matched) return
  activeSessionId.value = matched.id
  activeSession.value = matched
  nextTick(scrollToBottom)
}

async function removeSession(sessionId) {
  await ElMessageBox.confirm('确认删除这条本地历史会话？', '删除确认', { type: 'warning' })
  deleteSession({ groupId: props.groupId, docId: docId.value || '', sessionId })
  hydrateSessions()
}

function appendMessage(role, content, extra = {}) {
  const messages = [...(activeSession.value.messages || []), { role, content, ...extra }]
  const nextTitle = activeSession.value.title === '新会话' && role === 'user'
    ? String(content || '').trim().slice(0, 24) || '新会话'
    : activeSession.value.title

  updateActiveSession({
    title: nextTitle,
    messages,
  })
  persistActiveSession()
  nextTick(scrollToBottom)
}

function updateLastAssistant(delta, done = false) {
  const messages = [...(activeSession.value.messages || [])]
  const reverseIndex = [...messages].reverse().findIndex((item) => item.role === 'assistant')
  if (reverseIndex < 0) return
  const index = messages.length - 1 - reverseIndex
  messages[index] = {
    ...messages[index],
    content: `${messages[index].content || ''}${delta || ''}`,
    streaming: !done,
  }
  updateActiveSession({ messages })
  persistActiveSession()
  nextTick(scrollToBottom)
}

function finalizeLastAssistant(content) {
  const messages = [...(activeSession.value.messages || [])]
  const reverseIndex = [...messages].reverse().findIndex((item) => item.role === 'assistant')
  if (reverseIndex < 0) {
    appendMessage('assistant', content, { streaming: false })
    return
  }
  const index = messages.length - 1 - reverseIndex
  messages[index] = { ...messages[index], content, streaming: false }
  updateActiveSession({ messages })
  persistActiveSession()
  nextTick(scrollToBottom)
}

function setRunStatus(status) {
  const runs = Array.isArray(activeSession.value.runs) ? [...activeSession.value.runs] : []
  if (!runs.length) return
  runs[0] = {
    ...runs[0],
    status,
    finishedAt: ['done', 'error', 'completed', 'failed'].includes(status) ? new Date().toISOString() : runs[0].finishedAt,
  }
  updateActiveSession({ runs })
  persistActiveSession()
}

function createTask(id, title, kind, subtitle = '', detail = '') {
  return { id, title, kind, subtitle, detail, status: 'running', usage: createUsage() }
}

function recomputeRunUsage(tasks = []) {
  return tasks.reduce((acc, task) => {
    const usage = normalizeUsage(task?.usage || {})
    acc.inputTokens += usage.inputTokens
    acc.outputTokens += usage.outputTokens
    acc.totalTokens += usage.totalTokens
    acc.latencyMs += usage.latencyMs
    acc.isEstimated = acc.isEstimated || usage.isEstimated
    return acc
  }, createUsage())
}

function upsertRunTask(taskPatch) {
  const runs = Array.isArray(activeSession.value.runs) ? [...activeSession.value.runs] : []
  if (!runs.length) return
  const run = cloneRun(runs[0])
  const tasks = Array.isArray(run.tasks) ? [...run.tasks] : []
  const index = tasks.findIndex((item) => item.id === taskPatch.id)

  if (index >= 0) {
    tasks[index] = {
      ...tasks[index],
      ...taskPatch,
      usage: normalizeUsage(taskPatch.usage ?? tasks[index].usage ?? {}),
    }
  } else {
    tasks.unshift({ ...taskPatch, usage: normalizeUsage(taskPatch.usage || {}) })
  }

  run.tasks = tasks
  run.usage = recomputeRunUsage(tasks)
  runs[0] = run
  updateActiveSession({ runs })
  persistActiveSession()
}

function appendRunEvent(event) {
  const runs = Array.isArray(activeSession.value.runs) ? [...activeSession.value.runs] : []
  if (!runs.length) return
  const run = cloneRun(runs[0])
  run.events = [{ id: `${Date.now()}-${Math.random().toString(16).slice(2, 6)}`, ...event }, ...(run.events || [])].slice(0, 120)
  runs[0] = run
  updateActiveSession({ runs })
  persistActiveSession()
}

function setRunEvidence(items) {
  const runs = Array.isArray(activeSession.value.runs) ? [...activeSession.value.runs] : []
  if (!runs.length) return
  const run = cloneRun(runs[0])
  run.evidence = Array.isArray(items) ? items.slice(0, 20) : []
  runs[0] = run
  updateActiveSession({ runs })
  persistActiveSession()
}

function startRun() {
  const run = createRun()
  updateActiveSession({
    runs: [run, ...(Array.isArray(activeSession.value.runs) ? activeSession.value.runs : [])].slice(0, 12),
  })
  persistActiveSession()
}

function formatSessionMeta(session) {
  const stamp = String(session.updatedAt || '').replace('T', ' ').slice(0, 16)
  return session.docId ? `${stamp} · ${session.docId}` : `${stamp} · 分组对话`
}

function scrollToBottom() {
  if (!chatWindowEl.value) return
  chatWindowEl.value.scrollTop = chatWindowEl.value.scrollHeight
}

function taskStatusType(status) {
  if (['done', 'completed'].includes(status)) return 'success'
  if (['error', 'failed'].includes(status)) return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function taskStatusLabel(status) {
  if (['done', 'completed'].includes(status)) return '已完成'
  if (['error', 'failed'].includes(status)) return '失败'
  if (status === 'running') return '执行中'
  return '待处理'
}

function runStatusText(status) {
  if (['done', 'completed'].includes(status)) return '回答完成'
  if (['error', 'failed'].includes(status)) return '运行失败'
  if (status === 'running') return '执行中'
  return '等待提问'
}

function messageRoleLabel(role) {
  if (role === 'assistant') return 'Agent'
  if (role === 'system') return 'System'
  return 'User'
}

function formatTokenNumber(value) {
  const num = Number(value || 0) || 0
  return num.toLocaleString('zh-CN')
}

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatLatency(value) {
  const ms = Number(value || 0)
  if (!ms) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

function summarizeEvidence(item) {
  return item?.raw ? JSON.stringify(item.raw).slice(0, 180) : '暂无摘要'
}

function renderMarkdown(content) {
  return markdown.render(String(content || ''))
}

function traceTone(status) {
  const normalized = normalizeTraceStatus(status)
  if (normalized === 'completed') return 'success'
  if (normalized === 'failed') return 'danger'
  if (normalized === 'running') return 'warning'
  return 'info'
}

function traceKindLabel(kind) {
  const map = {
    llm: 'LLM',
    tool: 'Tool',
    skill: 'Skill',
    retrieval: 'Retrieval',
    assistant: 'Assistant',
    run: 'Run',
    event: 'Event',
    system: 'System',
    agent: 'Agent',
  }
  return map[kind] || String(kind || 'Trace')
}

function tracePrimaryText(step) {
  return [
    step?.error?.message,
    step?.payload?.message,
    step?.payload?.content_preview,
    step?.payload?.reply,
    step?.payload?.query,
    step?.payload?.description,
    step?.payload?.detail,
  ].find(Boolean) || ''
}

function traceEvidenceItems(step) {
  const items = step?.payload?.items_preview || step?.payload?.items || []
  return Array.isArray(items) ? items.slice(0, 6) : []
}

function tracePayloadEntries(step) {
  const payload = step?.payload && typeof step.payload === 'object' ? step.payload : {}
  const skipKeys = new Set(['items', 'items_preview', 'reply', 'content', 'content_preview', 'message', 'detail', 'description', 'delta'])

  return Object.entries(payload)
    .filter(([key, value]) => !skipKeys.has(key) && value !== undefined && value !== null && value !== '')
    .slice(0, 10)
    .map(([key, value]) => {
      if (typeof value === 'object') {
        const rendered = JSON.stringify(value, null, 2)
        return { key, value: rendered, multiline: true }
      }
      const rendered = String(value)
      return { key, value: rendered, multiline: rendered.length > 120 || rendered.includes('\n') }
    })
}

function handleTraceEventPayload(step, payload) {
  if (step.event === 'assistant.start') {
    appendMessage('assistant', '', { streaming: true })
    return
  }

  if (step.event === 'assistant.chunk') {
    updateLastAssistant(step.payload?.delta || '', false)
    return
  }

  if (step.event === 'assistant.done' || step.event === 'done') {
    finalizeLastAssistant(step.payload?.content || step.payload?.reply || payload?.content || '')
    setRunStatus('done')
    return
  }

  if (step.status === 'failed' && (step.kind === 'assistant' || step.event === 'trace.ready')) {
    setRunStatus('error')
  }
}

function handleAgentEvent(eventName, payload) {
  if (eventName === 'trace' && payload?.step) {
    const step = normalizeTraceStep({
      ...payload.step,
      trace_id: payload.trace_id || payload.step?.trace_id,
      payload: { ...(payload.step?.payload || {}), ...(payload.payload || {}) },
    })
    upsertTraceStep(step)
    handleTraceEventPayload(step, payload)
    return
  }

  const event = payload && typeof payload === 'object' ? payload : { raw: payload }

  switch (eventName) {
    case 'run.start':
      appendRunEvent({ title: '开始执行', description: 'Agent 已接收问题并开始规划。', tone: 'info' })
      break
    case 'agent.think.start':
      upsertRunTask(createTask(
        event.task_id || `agent-think:${Date.now()}`,
        'Agent 推理',
        'agent',
        event.model_name || 'LLM',
        `messages=${event.message_count || 0}`,
      ))
      appendRunEvent({ title: '模型开始推理', description: `输入消息数：${event.message_count || 0}`, tone: 'warning' })
      break
    case 'agent.tool_calls':
      ;(event.tool_calls || []).forEach((call, index) => {
        upsertRunTask(createTask(
          call.id || `${call.name}-${index}`,
          call.name || 'tool',
          'tool',
          '等待执行',
          JSON.stringify(call.args || {}, null, 2),
        ))
      })
      appendRunEvent({
        title: '模型规划了工具调用',
        description: `${(event.tool_calls || []).map((item) => item.name).join('、') || '无工具'}`,
        tone: 'info',
      })
      break
    case 'tool.start':
      upsertRunTask(createTask(`tool:${event.tool_name}`, event.tool_name || 'tool', 'tool', '开始执行', event.query || event.group_id || ''))
      appendRunEvent({ title: `开始执行 ${event.tool_name}`, description: event.query || '', tone: 'warning' })
      break
    case 'tool.end':
      upsertRunTask({
        id: `tool:${event.tool_name}`,
        title: event.tool_name || 'tool',
        kind: 'tool',
        subtitle: `返回 ${event.items ?? event.steps ?? 0} 条结果`,
        detail: event.content_preview || '',
        status: 'done',
      })
      if (Array.isArray(event.items_preview) && event.items_preview.length) setRunEvidence(event.items_preview)
      appendRunEvent({
        title: `${event.tool_name} 执行完成`,
        description: `steps=${event.steps ?? 0}，items=${event.items ?? 0}，errors=${event.errors ?? 0}`,
        tone: 'success',
      })
      break
    case 'tool.error':
      upsertRunTask({
        id: `tool:${event.tool_name}`,
        title: event.tool_name || 'tool',
        kind: 'tool',
        subtitle: '执行失败',
        detail: event.error || '',
        status: 'error',
      })
      appendRunEvent({ title: `${event.tool_name} 执行失败`, description: event.error || '', tone: 'danger' })
      break
    case 'skill.load.start':
      upsertRunTask(createTask(`skill:load:${event.skill_name}`, `加载技能 ${event.skill_name}`, 'skill', '读取说明'))
      appendRunEvent({ title: `开始加载技能 ${event.skill_name}`, description: '', tone: 'info' })
      break
    case 'skill.load.end':
      upsertRunTask({
        id: `skill:load:${event.skill_name}`,
        title: `加载技能 ${event.skill_name}`,
        kind: 'skill',
        subtitle: '说明已加载',
        detail: event.content_preview || '',
        status: 'done',
      })
      break
    case 'skill.file.start':
      upsertRunTask(createTask(`skill:file:${event.skill_name}:${event.filename}`, `读取技能文件 ${event.filename}`, 'skill', event.skill_name))
      break
    case 'skill.file.end':
      upsertRunTask({
        id: `skill:file:${event.skill_name}:${event.filename}`,
        title: `读取技能文件 ${event.filename}`,
        kind: 'skill',
        subtitle: event.skill_name,
        detail: event.content_preview || '',
        status: 'done',
      })
      break
    case 'skill.script.start':
      upsertRunTask(createTask(`skill:script:${event.skill_name}:${event.script_name}`, `执行脚本 ${event.script_name}`, 'skill', event.skill_name, event.script_args || ''))
      break
    case 'skill.script.end':
      upsertRunTask({
        id: `skill:script:${event.skill_name}:${event.script_name}`,
        title: `执行脚本 ${event.script_name}`,
        kind: 'skill',
        subtitle: event.skill_name,
        detail: event.content_preview || '',
        status: 'done',
      })
      break
    case 'retrieval.plan.start':
      appendRunEvent({ title: '开始执行检索计划', description: `共 ${event.step_count || 0} 步`, tone: 'warning' })
      break
    case 'retrieval.step.start':
      upsertRunTask(createTask(`retrieval:${event.step}`, `${event.label || `step_${event.step}`}`, 'retrieval', event.mode, event.query || ''))
      break
    case 'retrieval.step.end':
      upsertRunTask({
        id: `retrieval:${event.step}`,
        title: `${event.label || `step_${event.step}`}`,
        kind: 'retrieval',
        subtitle: `${event.mode} · 命中 ${event.raw_count || 0} 条`,
        detail: event.query || '',
        status: 'done',
      })
      appendRunEvent({
        title: `检索步骤 ${event.step} 完成`,
        description: `${event.mode} 命中 ${event.raw_count || 0} 条`,
        tone: 'success',
      })
      break
    case 'retrieval.step.error':
      upsertRunTask({
        id: `retrieval:${event.step}`,
        title: `${event.label || `step_${event.step}`}`,
        kind: 'retrieval',
        subtitle: '检索失败',
        detail: event.error || '',
        status: 'error',
      })
      appendRunEvent({ title: `检索步骤 ${event.step} 失败`, description: event.error || '', tone: 'danger' })
      break
    case 'usage.llm':
      upsertRunTask({
        id: event.task_id || `agent-think:${Date.now()}`,
        title: 'Agent 推理',
        kind: 'agent',
        subtitle: event.model_name || event.provider || 'LLM',
        detail: `${event.provider || ''}${event.latency_ms ? ` · ${event.latency_ms}ms` : ''}`,
        status: 'done',
        usage: normalizeUsage(event),
      })
      appendRunEvent({
        title: 'Token 使用统计',
        description: `in=${formatTokenNumber(event.input_tokens)} out=${formatTokenNumber(event.output_tokens)} total=${formatTokenNumber(event.total_tokens)}`,
        tone: 'info',
      })
      break
    case 'assistant.start':
      appendMessage('assistant', '', { streaming: true })
      break
    case 'assistant.chunk':
      updateLastAssistant(event.delta || '', false)
      break
    case 'assistant.done':
      finalizeLastAssistant(event.content || '')
      setRunStatus('done')
      appendRunEvent({ title: '回答已完成', description: '最终回复已写入会话。', tone: 'success' })
      break
    case 'agent.error':
      setRunStatus('error')
      appendRunEvent({ title: 'Agent 运行异常', description: event.error || '', tone: 'danger' })
      break
    case 'run.failed':
      setRunStatus('error')
      break
    default:
      appendRunEvent({
        title: eventName,
        description: typeof payload === 'string' ? payload : JSON.stringify(payload || {}).slice(0, 180),
        tone: 'info',
      })
  }
}

function upsertTraceStep(rawStep) {
  const runs = Array.isArray(activeSession.value.runs) ? [...activeSession.value.runs] : []
  if (!runs.length) return
  const run = cloneRun(runs[0])
  const traceSteps = Array.isArray(run.traceSteps) ? [...run.traceSteps] : []
  const step = normalizeTraceStep(rawStep)
  const index = traceSteps.findIndex((item) => item.step_id === step.step_id)

  if (index >= 0) {
    traceSteps[index] = { ...traceSteps[index], ...step }
  } else {
    traceSteps.push(step)
  }

  run.traceSteps = traceSteps.slice(-300)
  if (step.trace_id) run.traceId = step.trace_id
  if (step.payload?.trace_path) run.tracePath = step.payload.trace_path

  if (step.status === 'failed') {
    run.status = 'failed'
    run.finishedAt = new Date().toISOString()
  } else if (['done', 'trace.ready', 'assistant.done'].includes(step.event) && step.status === 'completed') {
    run.status = 'completed'
    run.finishedAt = new Date().toISOString()
  } else if (run.status === 'idle') {
    run.status = 'running'
  }

  runs[0] = run
  updateActiveSession({ runs })
  persistActiveSession()
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

async function send() {
  const t = (text.value || '').trim()
  if (!t || sending.value) return

  appendMessage('user', t)
  text.value = ''
  sending.value = true
  startRun()

  try {
    await postEventStream(
      '/agent/stream',
      {
        group_id: props.groupId,
        doc_id: docId.value || null,
        user_text: t,
      },
      { onEvent: handleAgentEvent },
    )
  } catch (e) {
    ElMessage.error(`请求失败: ${e?.message || e}`)
    appendRunEvent({ title: '请求失败', description: `${e?.message || e}`, tone: 'danger' })
    setRunStatus('error')
    appendMessage('assistant', `请求失败：${e?.message || e}`)
  } finally {
    sending.value = false
  }
}

watch(
  () => docId.value,
  () => {
    hydrateSessions()
    nextTick(scrollToBottom)
  },
)

onMounted(async () => {
  await loadDocs()
  hydrateSessions()
  nextTick(scrollToBottom)
})
</script>

<style scoped>
.agent-workbench {
  display: grid;
  grid-template-columns: 260px minmax(780px, 1.7fr) minmax(360px, 0.82fr);
  gap: 16px;
  align-items: start;
}

.session-panel,
.chat-panel,
.observe-panel {
  min-width: 0;
}

.session-panel__header,
.agent-header,
.observe-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.scope-chip {
  margin-bottom: 14px;
  padding: 16px 18px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(29, 92, 99, 0.14), rgba(207, 122, 73, 0.08));
}

.scope-chip__label {
  display: block;
  font-size: 12px;
  color: var(--text-faint);
}

.scope-chip__value {
  display: block;
  margin-top: 8px;
  color: var(--brand-strong);
  font-size: 15px;
}

.session-list {
  display: grid;
  gap: 10px;
  max-height: 760px;
  overflow: auto;
}

.session-item {
  display: grid;
  gap: 8px;
  width: 100%;
  padding: 15px;
  border-radius: 18px;
  border: 1px solid rgba(20, 48, 61, 0.1);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 244, 238, 0.94));
  text-align: left;
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}

.session-item:hover,
.session-item.is-active {
  transform: translateY(-1px);
  border-color: rgba(29, 92, 99, 0.34);
  box-shadow: 0 12px 28px rgba(21, 48, 63, 0.08);
}

.session-item__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.session-item__title {
  font-weight: 700;
  line-height: 1.5;
  color: var(--brand-strong);
}

.session-item__meta,
.session-item__stats {
  font-size: 12px;
  color: var(--text-sub);
}

.session-item__stats {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.agent-header__actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.agent-doc-select {
  width: 320px;
}

.chat-shell {
  display: grid;
  grid-template-rows: 1fr auto;
  gap: 16px;
  min-height: 760px;
}

.chat-window {
  display: grid;
  align-content: start;
  gap: 14px;
  min-height: 0;
  max-height: 840px;
  overflow: auto;
  padding: 16px;
  border-radius: 24px;
  border: 1px solid rgba(22, 50, 64, 0.08);
  background:
    radial-gradient(circle at top left, rgba(246, 196, 90, 0.18), transparent 20%),
    linear-gradient(180deg, rgba(248, 243, 235, 0.92), rgba(255, 255, 255, 0.96));
}

.chat-window__hero {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(200px, 0.8fr);
  gap: 16px;
  padding: 20px;
  border-radius: 22px;
  background: linear-gradient(135deg, #173548 0%, #24596b 58%, #f6efe3 58%, #fcfaf6 100%);
  color: #eff7fb;
}

.chat-window__hero h3 {
  margin: 10px 0 8px;
  font-size: 26px;
  line-height: 1.15;
}

.chat-window__hero p {
  margin: 0;
  line-height: 1.7;
  color: rgba(239, 247, 251, 0.84);
}

.chat-window__meta {
  display: grid;
  gap: 10px;
  align-content: center;
}

.hero-stat {
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 251, 244, 0.84);
  color: #1a2b35;
}

.hero-stat span {
  display: block;
  font-size: 12px;
  color: #67727a;
}

.hero-stat strong {
  display: block;
  margin-top: 6px;
  font-size: 24px;
}

.chat-bubble {
  max-width: min(980px, 96%);
  padding: 16px 18px;
  border-radius: 20px;
  border: 1px solid rgba(17, 40, 55, 0.1);
  background: #fffdf9;
  box-shadow: 0 10px 24px rgba(23, 45, 61, 0.04);
}

.chat-bubble.is-user {
  justify-self: end;
  background: linear-gradient(180deg, rgba(29, 92, 99, 0.12), rgba(29, 92, 99, 0.08));
}

.chat-bubble.is-assistant {
  justify-self: start;
}

.chat-bubble.is-system {
  justify-self: center;
  max-width: 100%;
  background: rgba(246, 196, 90, 0.12);
}

.chat-bubble__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.chat-bubble__role {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--text-faint);
}

.chat-bubble__content {
  line-height: 1.78;
  color: var(--text-main);
}

.chat-bubble__content :deep(*) {
  max-width: 100%;
}

.chat-bubble__content :deep(p) {
  margin: 0 0 0.9em;
}

.chat-bubble__content :deep(p:last-child) {
  margin-bottom: 0;
}

.chat-bubble__content :deep(h1),
.chat-bubble__content :deep(h2),
.chat-bubble__content :deep(h3),
.chat-bubble__content :deep(h4) {
  margin: 0.2em 0 0.6em;
  line-height: 1.3;
  color: var(--brand-strong);
}

.chat-bubble__content :deep(ul),
.chat-bubble__content :deep(ol) {
  margin: 0.6em 0;
  padding-left: 1.4em;
}

.chat-bubble__content :deep(li) {
  margin: 0.25em 0;
}

.chat-bubble__content :deep(blockquote) {
  margin: 0.8em 0;
  padding: 0.2em 0 0.2em 1em;
  border-left: 3px solid rgba(29, 92, 99, 0.28);
  color: var(--text-sub);
  background: rgba(29, 92, 99, 0.04);
  border-radius: 0 12px 12px 0;
}

.chat-bubble__content :deep(pre) {
  margin: 0.9em 0;
  padding: 14px 16px;
  overflow: auto;
  border-radius: 16px;
  background: #12202b;
  color: #eaf4f8;
}

.chat-bubble__content :deep(code) {
  padding: 0.12em 0.38em;
  border-radius: 6px;
  background: rgba(18, 32, 43, 0.08);
  font-family: Consolas, 'Courier New', monospace;
  font-size: 0.92em;
}

.chat-bubble__content :deep(pre code) {
  padding: 0;
  background: transparent;
  color: inherit;
}

.chat-bubble__content :deep(a) {
  color: #1b6781;
  text-decoration: none;
  border-bottom: 1px dashed rgba(27, 103, 129, 0.35);
}

.chat-bubble__content :deep(table) {
  width: 100%;
  margin: 0.9em 0;
  border-collapse: collapse;
  overflow: hidden;
  border-radius: 12px;
}

.chat-bubble__content :deep(th),
.chat-bubble__content :deep(td) {
  padding: 10px 12px;
  border: 1px solid rgba(20, 48, 61, 0.08);
  text-align: left;
}

.chat-bubble__content :deep(th) {
  background: rgba(29, 92, 99, 0.08);
  color: var(--brand-strong);
}

.streaming-dot {
  font-size: 12px;
  color: var(--accent);
}

.chat-compose {
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 22px;
  border: 1px solid rgba(20, 48, 61, 0.08);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(246, 241, 234, 0.96));
}

.compose-input :deep(.el-textarea__inner) {
  min-height: 120px !important;
}

.chat-compose__actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.brand-button {
  border: 0;
  border-radius: 14px;
  padding-inline: 18px;
  background: linear-gradient(135deg, #1d5c63 0%, #3c7b67 100%);
  box-shadow: 0 10px 24px rgba(29, 92, 99, 0.22);
}

.brand-button:hover {
  opacity: 0.95;
}

.ghost-button {
  border-radius: 14px;
  border-color: rgba(29, 92, 99, 0.18);
  background: rgba(255, 255, 255, 0.84);
  color: var(--brand-strong);
}

.send-button {
  min-width: 140px;
}

.observe-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.observe-metric {
  padding: 14px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(29, 92, 99, 0.1), rgba(29, 92, 99, 0.04));
}

.observe-metric span {
  display: block;
  font-size: 12px;
  color: var(--text-sub);
}

.observe-metric strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
  color: var(--brand-strong);
}

.usage-metric {
  background: linear-gradient(180deg, rgba(16, 62, 82, 0.12), rgba(16, 62, 82, 0.05));
}

.trace-shell {
  display: grid;
  gap: 14px;
}

.trace-overview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  padding: 16px;
  border: 1px solid rgba(20, 48, 61, 0.08);
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(246, 248, 250, 0.95));
}

.trace-overview__label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-faint);
}

.trace-overview__id {
  margin-top: 8px;
  font-size: 13px;
  color: var(--brand-strong);
  word-break: break-all;
}

.trace-overview__meta,
.trace-overview__time {
  margin-top: 10px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-sub);
}

.trace-overview__side {
  display: grid;
  align-content: space-between;
  justify-items: end;
}

.trace-timeline {
  display: grid;
  gap: 14px;
  max-height: 840px;
  overflow: auto;
  padding-right: 4px;
}

.trace-card {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.trace-card__rail {
  display: grid;
  justify-items: center;
  align-self: stretch;
}

.trace-card__dot {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: #7c95a5;
  box-shadow: 0 10px 18px rgba(19, 37, 50, 0.12);
}

.trace-card__dot.is-success {
  background: #1f9d55;
}

.trace-card__dot.is-warning {
  background: #d99100;
}

.trace-card__dot.is-danger {
  background: #cc3d3d;
}

.trace-card__line {
  width: 2px;
  flex: 1 1 auto;
  min-height: 52px;
  margin-top: 6px;
  background: linear-gradient(180deg, rgba(29, 92, 99, 0.24), rgba(29, 92, 99, 0.06));
}

.trace-card__body {
  display: grid;
  gap: 10px;
  padding: 16px;
  border-radius: 20px;
  border: 1px solid rgba(20, 48, 61, 0.08);
  background: rgba(255, 255, 255, 0.96);
}

.trace-card.is-success .trace-card__body {
  border-color: rgba(31, 157, 85, 0.22);
}

.trace-card.is-warning .trace-card__body {
  border-color: rgba(217, 145, 0, 0.22);
}

.trace-card.is-danger .trace-card__body {
  border-color: rgba(204, 61, 61, 0.22);
}

.trace-card__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.trace-card__title-wrap {
  min-width: 0;
}

.trace-card__eyebrow {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-faint);
}

.trace-card__title {
  margin-top: 4px;
  font-size: 16px;
  font-weight: 700;
  color: var(--brand-strong);
  line-height: 1.4;
}

.trace-card__subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-sub);
}

.trace-card__meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-sub);
}

.trace-card__desc,
.trace-evidence-card__content,
.trace-payload-item__value {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-main);
  white-space: pre-wrap;
  word-break: break-word;
}

.trace-card__error {
  padding: 10px 12px;
  border-radius: 14px;
  background: #fff1f1;
  border: 1px solid #ffd7d7;
  color: #9c2323;
  font-size: 12px;
  line-height: 1.6;
}

.trace-card__section {
  display: grid;
  gap: 10px;
}

.trace-card__section-title {
  font-size: 12px;
  font-weight: 700;
  color: #4f6674;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.trace-evidence-card {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(20, 48, 61, 0.08);
  background: linear-gradient(180deg, rgba(251, 252, 253, 0.98), rgba(246, 248, 250, 0.94));
}

.trace-evidence-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.trace-evidence-card__meta {
  font-size: 11px;
  color: var(--text-faint);
}

.trace-evidence-card__title {
  font-weight: 700;
  color: var(--brand-strong);
}

.trace-payload-list {
  display: grid;
  gap: 8px;
}

.trace-payload-item {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 14px;
  background: #f7fafc;
  border: 1px solid #dde7ee;
}

.trace-payload-item__key {
  font-size: 12px;
  font-weight: 700;
  color: #4d6674;
}

.trace-payload-item__value {
  margin: 0;
  font-family: Consolas, 'Courier New', monospace;
}

.mono {
  font-family: Consolas, 'Courier New', monospace;
}

.empty-state {
  padding: 24px;
  border-radius: 18px;
  border: 1px dashed rgba(20, 48, 61, 0.14);
  background: rgba(247, 250, 252, 0.92);
  color: var(--text-sub);
  text-align: center;
}

@media (max-width: 1680px) {
  .agent-workbench {
    grid-template-columns: 260px minmax(0, 1fr);
  }

  .observe-panel {
    grid-column: 1 / -1;
  }
}

@media (min-width: 1681px) {
  .observe-panel {
    position: sticky;
    top: 16px;
  }
}

@media (max-width: 1100px) {
  .agent-workbench {
    grid-template-columns: 1fr;
  }

  .chat-window__hero,
  .trace-overview {
    grid-template-columns: 1fr;
  }

  .observe-summary {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .agent-header,
  .observe-header,
  .session-panel__header {
    flex-direction: column;
  }

  .agent-doc-select {
    width: 100%;
  }

  .chat-compose__actions {
    flex-direction: column;
  }

  .trace-card {
    grid-template-columns: 1fr;
  }

  .trace-card__rail {
    grid-auto-flow: column;
    justify-content: start;
    gap: 8px;
  }

  .trace-card__line {
    width: 32px;
    height: 2px;
    min-height: 0;
    margin-top: 13px;
  }
}
</style>
