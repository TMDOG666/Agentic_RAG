<template>
  <div class="agent-workbench">
    <el-card shadow="never" class="view-card session-panel">
      <template #header>
        <div class="session-panel__header">
          <div>
            <div class="section-title">会话历史</div>
            <div class="section-subtitle">当前历史只保存在浏览器本地，后续可以独立拆除。</div>
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
            <span>{{ Math.max(0, session.messages.length - 1) }} 条消息</span>
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
            <div class="section-subtitle">中间展示流式回复，右侧展示 tool、skill、检索步骤和任务表。</div>
          </div>
          <div class="agent-header__actions">
            <el-select v-model="docId" clearable placeholder="可选：绑定 doc_id" class="glass-select agent-doc-select">
              <el-option v-for="d in docs" :key="d.doc_id" :label="`${d.doc_name} (${d.doc_id})`" :value="d.doc_id" />
            </el-select>
            <el-button class="ghost-button" @click="loadDocs" :loading="docsLoading">刷新文档</el-button>
          </div>
        </div>
      </template>

      <div class="chat-shell">
        <section ref="chatWindowEl" class="chat-window">
          <div class="chat-window__hero">
            <div>
              <div class="eyebrow">Agent Stream</div>
              <h3>流式回答 + 执行观测</h3>
              <p>当前会话会同步展示 Agent 的思考阶段、tool 调用、skill 读取、检索步骤和证据摘要。</p>
            </div>
            <div class="chat-window__meta">
              <div class="hero-stat">
                <span>运行状态</span>
                <strong>{{ runStatusLabel }}</strong>
              </div>
              <div class="hero-stat">
                <span>任务数</span>
                <strong>{{ currentRun.tasks.length }}</strong>
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
            <div class="section-title">执行观测</div>
            <div class="section-subtitle">采用通用侧边栏方案，统一展示任务表、事件流和证据卡。</div>
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

      <el-tabs v-model="activeObserveTab" class="observe-tabs">
        <el-tab-pane label="任务表" name="tasks">
          <div v-if="!currentRun.tasks.length" class="empty-state">本次会话还没有执行任务。</div>
          <div v-else class="task-list">
            <div v-for="task in currentRun.tasks" :key="task.id" class="task-item" :class="`is-${task.status}`">
              <div class="task-item__head">
                <div>
                  <div class="task-item__title">{{ task.title }}</div>
                  <div class="task-item__meta">{{ task.kind }} · {{ task.subtitle || '处理中' }}</div>
                </div>
                <el-tag :type="taskStatusType(task.status)" effect="light" round>{{ taskStatusLabel(task.status) }}</el-tag>
              </div>
              <div class="task-usage">
                <span class="task-usage__item">In {{ formatTokenNumber(task.usage?.inputTokens) }}</span>
                <span class="task-usage__item">Out {{ formatTokenNumber(task.usage?.outputTokens) }}</span>
                <span class="task-usage__item">Total {{ formatTokenNumber(task.usage?.totalTokens) }}</span>
                <span v-if="task.usage?.isEstimated" class="task-usage__hint">估算</span>
              </div>
              <div v-if="task.detail" class="task-item__detail">{{ task.detail }}</div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="过程流" name="events">
          <div v-if="!currentRun.events.length" class="empty-state">发送问题后，这里会出现 Agent 的执行过程。</div>
          <div v-else class="event-list">
            <div v-for="event in currentRun.events" :key="event.id" class="event-item">
              <div class="event-item__dot" :class="`is-${event.tone}`" />
              <div class="event-item__body">
                <div class="event-item__title">{{ event.title }}</div>
                <div v-if="event.description" class="event-item__desc">{{ event.description }}</div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="证据卡" name="evidence">
          <div v-if="!currentRun.evidence.length" class="empty-state">检索命中的文档片段会显示在这里。</div>
          <div v-else class="evidence-list">
            <article
              v-for="(item, idx) in currentRun.evidence"
              :key="`${idx}-${item.chunk_id || item.entity_name || item.relation}`"
              class="evidence-card"
            >
              <div class="evidence-card__head">
                <el-tag size="small" effect="plain">{{ item.mode || item.type || 'evidence' }}</el-tag>
                <span class="mono evidence-card__meta">{{ item.document_name || item.doc_id || 'unknown-doc' }}</span>
              </div>
              <div class="evidence-card__title">{{ item.entity_name || item.relation || item.chunk_id || '检索命中' }}</div>
              <div class="evidence-card__content">{{ item.text || summarizeEvidence(item) }}</div>
            </article>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { api, postEventStream } from '../../lib/api'
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
const activeObserveTab = ref('tasks')

const sessions = ref([])
const activeSessionId = ref('')
const activeSession = ref(createEphemeralSession({ groupId: props.groupId, docId: '' }))
const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const scopeLabel = computed(() => (docId.value ? `分组 ${props.groupId} / 文档 ${docId.value}` : `分组 ${props.groupId} / 全局`))
const activeMessages = computed(() => activeSession.value?.messages || [])
const currentRun = computed(() => {
  const runs = Array.isArray(activeSession.value?.runs) ? activeSession.value.runs : []
  const run = runs[0]
  if (!run) return createRunState()
  return {
    ...createRunState(),
    ...run,
    usage: createUsage(run.usage || {}),
    tasks: Array.isArray(run.tasks)
      ? run.tasks.map((task) => ({ ...task, usage: createUsage(task?.usage || {}) }))
      : [],
  }
})
const runStatusLabel = computed(() => runStatusText(currentRun.value.status))
const runStatusType = computed(() => taskStatusType(currentRun.value.status))

function createRunState() {
  return {
    id: '',
    status: 'idle',
    startedAt: '',
    finishedAt: '',
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
  return createUsage({
    inputTokens: Number(payload.input_tokens ?? payload.inputTokens ?? 0) || 0,
    outputTokens: Number(payload.output_tokens ?? payload.outputTokens ?? 0) || 0,
    totalTokens: Number(payload.total_tokens ?? payload.totalTokens ?? 0) || 0,
    isEstimated: Boolean(payload.is_estimated ?? payload.isEstimated),
    latencyMs: Number(payload.latency_ms ?? payload.latencyMs ?? 0) || 0,
  })
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
  activeObserveTab.value = 'tasks'
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
  updateActiveSession({
    title: activeSession.value.title === '新会话' && role === 'user'
      ? String(content || '').trim().slice(0, 24) || '新会话'
      : activeSession.value.title,
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
    finishedAt: ['done', 'error'].includes(status) ? new Date().toISOString() : runs[0].finishedAt,
  }
  updateActiveSession({ runs })
  persistActiveSession()
}

function createTask(id, title, kind, subtitle = '', detail = '') {
  return { id, title, kind, subtitle, detail, status: 'running', usage: createUsage() }
}

function recomputeRunUsage(tasks = []) {
  return tasks.reduce(
    (acc, task) => {
      const usage = normalizeUsage(task?.usage || {})
      acc.inputTokens += usage.inputTokens
      acc.outputTokens += usage.outputTokens
      acc.totalTokens += usage.totalTokens
      acc.latencyMs += usage.latencyMs
      acc.isEstimated = acc.isEstimated || usage.isEstimated
      return acc
    },
    createUsage(),
  )
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
  }
  else tasks.unshift({ ...taskPatch, usage: normalizeUsage(taskPatch.usage || {}) })
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
  if (status === 'done') return 'success'
  if (status === 'error') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function taskStatusLabel(status) {
  if (status === 'done') return '已完成'
  if (status === 'error') return '失败'
  if (status === 'running') return '执行中'
  return '待处理'
}

function runStatusText(status) {
  if (status === 'done') return '回答完成'
  if (status === 'error') return '运行失败'
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

function summarizeEvidence(item) {
  return item?.raw ? JSON.stringify(item.raw).slice(0, 180) : '暂无摘要'
}

function renderMarkdown(content) {
  return markdown.render(String(content || ''))
}

function handleAgentEvent(eventName, payload) {
  const event = payload && typeof payload === 'object' ? payload : { raw: payload }

  switch (eventName) {
    case 'run.start':
      appendRunEvent({ title: '已开始执行', description: 'Agent 已接收问题并开始规划。', tone: 'info' })
      break
    case 'agent.think.start':
      upsertRunTask(
        createTask(
          event.task_id || `agent-think:${Date.now()}`,
          'Agent 推理',
          'agent',
          event.model_name || 'LLM',
          `messages=${event.message_count || 0}`,
        ),
      )
      appendRunEvent({ title: '模型开始推理', description: `输入消息数：${event.message_count || 0}`, tone: 'warning' })
      break
    case 'agent.tool_calls':
      ;(event.tool_calls || []).forEach((call, index) => {
        upsertRunTask(createTask(call.id || `${call.name}-${index}`, call.name || 'tool', 'tool', '等待执行', JSON.stringify(call.args || {}, null, 2)))
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
      activeObserveTab.value = 'tasks'
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
      if (Array.isArray(event.items_preview) && event.items_preview.length) {
        setRunEvidence(event.items_preview)
        activeObserveTab.value = 'evidence'
      }
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
      activeObserveTab.value = 'events'
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
  activeObserveTab.value = 'tasks'

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
  grid-template-columns: 260px minmax(780px, 1.7fr) minmax(320px, 0.72fr);
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
  background:
    linear-gradient(135deg, #173548 0%, #24596b 58%, #f6efe3 58%, #fcfaf6 100%);
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

.observe-tabs :deep(.el-tabs__content) {
  padding-top: 6px;
}

.task-list,
.event-list,
.evidence-list {
  display: grid;
  gap: 12px;
  max-height: 640px;
  overflow: auto;
  padding-right: 4px;
}

.task-item,
.evidence-card {
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid rgba(20, 48, 61, 0.08);
  background: rgba(255, 255, 255, 0.94);
}

.task-item.is-running {
  border-color: rgba(194, 134, 41, 0.28);
}

.task-item.is-done {
  border-color: rgba(59, 143, 104, 0.24);
}

.task-item.is-error {
  border-color: rgba(188, 78, 82, 0.24);
}

.task-item__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.task-item__title {
  font-weight: 700;
  color: var(--brand-strong);
}

.task-item__meta,
.task-item__detail,
.event-item__desc,
.evidence-card__content {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-sub);
  white-space: pre-wrap;
  word-break: break-word;
}

.task-usage {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.task-usage__item,
.task-usage__hint {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.4;
  background: rgba(17, 40, 55, 0.06);
  color: var(--text-sub);
}

.task-usage__hint {
  background: rgba(194, 134, 41, 0.14);
  color: #8b5b11;
}

.event-item {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 8px 2px;
}

.event-item__dot {
  width: 10px;
  height: 10px;
  margin-top: 6px;
  border-radius: 999px;
  background: #8aa0af;
}

.event-item__dot.is-success {
  background: var(--success);
}

.event-item__dot.is-warning {
  background: var(--warning);
}

.event-item__dot.is-danger {
  background: var(--danger);
}

.event-item__title {
  font-weight: 700;
  color: var(--text-main);
}

.evidence-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.evidence-card__meta {
  font-size: 11px;
  color: var(--text-faint);
}

.evidence-card__title {
  margin-top: 10px;
  font-weight: 700;
  color: var(--brand-strong);
}

@media (max-width: 1680px) {
  .agent-workbench {
    grid-template-columns: 260px minmax(0, 1fr);
  }

  .observe-panel {
    grid-column: 1 / -1;
  }

  .observe-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
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

  .chat-window__hero {
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
}
</style>
