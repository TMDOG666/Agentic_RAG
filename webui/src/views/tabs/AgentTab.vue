<template>
  <div class="agent-layout">
    <el-card shadow="never" class="view-card session-panel">
      <template #header>
        <div class="session-panel__header">
          <div>
            <div class="section-title">会话历史</div>
            <div class="section-subtitle">仅保存在当前浏览器本地，后续要移除时只需删除前端历史模块。</div>
          </div>
          <el-button type="primary" @click="startNewSession">新建会话</el-button>
        </div>
      </template>

      <div class="session-filter">
        <div class="session-filter__label">当前范围</div>
        <div class="session-filter__value">{{ scopeLabel }}</div>
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
          <div class="session-item__count">{{ session.messages.length - 1 }} 条消息</div>
        </button>
      </div>
    </el-card>

    <el-card shadow="never" class="view-card">
      <template #header>
        <div class="agent-header">
          <div>
            <div class="section-title">Agent 对话</div>
            <div class="section-subtitle">可以绑定到某个文档，也可以直接对整个分组提问。</div>
          </div>
          <div class="agent-header__actions">
            <el-select v-model="docId" clearable placeholder="可选：绑定 doc_id" class="glass-select" style="width: 320px">
              <el-option v-for="d in docs" :key="d.doc_id" :label="`${d.doc_name} (${d.doc_id})`" :value="d.doc_id" />
            </el-select>
            <el-button @click="loadDocs" :loading="docsLoading">刷新文档</el-button>
          </div>
        </div>
      </template>

      <div class="agent-panel">
        <div ref="chatWindowEl" class="chat-window">
          <div v-for="(m, idx) in activeMessages" :key="`${idx}-${m.role}`" class="chat-bubble" :class="`is-${m.role}`">
            <div class="chat-bubble__role">{{ m.role }}</div>
            <div class="chat-bubble__content">{{ m.content }}</div>
          </div>
        </div>

        <div class="chat-compose">
          <el-input
            v-model="text"
            type="textarea"
            :rows="3"
            placeholder="输入问题，回车发送。"
            class="glass-input"
            @keydown.enter.exact.prevent="send"
          />
          <el-button type="primary" :loading="sending" @click="send">发送</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../lib/api'
import {
  createEphemeralSession,
  createSession,
  deleteSession,
  listSessions,
  upsertSession,
} from '../../modules/agent-chat-history'

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

const scopeLabel = computed(() => (docId.value ? `分组 ${props.groupId} / 文档 ${docId.value}` : `分组 ${props.groupId} / 全局`))
const activeMessages = computed(() => activeSession.value?.messages || [])

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

function appendMessage(role, content) {
  activeSession.value = {
    ...activeSession.value,
    title:
      activeSession.value.title === '新会话' && role === 'user'
        ? String(content || '').trim().slice(0, 24) || '新会话'
        : activeSession.value.title,
    messages: [...(activeSession.value.messages || []), { role, content }],
  }
  persistActiveSession()
  nextTick(scrollToBottom)
}

function formatSessionMeta(session) {
  const stamp = String(session.updatedAt || '').replace('T', ' ').slice(0, 16)
  return session.docId ? `${stamp} · ${session.docId}` : `${stamp} · 分组对话`
}

function scrollToBottom() {
  if (!chatWindowEl.value) return
  chatWindowEl.value.scrollTop = chatWindowEl.value.scrollHeight
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
  if (!t) return

  appendMessage('user', t)
  text.value = ''

  sending.value = true
  try {
    const payload = {
      group_id: props.groupId,
      doc_id: docId.value || null,
      user_text: t,
    }
    const res = await api.post('/agent/run', payload)
    appendMessage('assistant', String(res.data?.reply || '') || 'Agent 未返回内容。')
  } catch (e) {
    ElMessage.error(`请求失败: ${e?.message || e}`)
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
.agent-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
}

.session-panel {
  min-width: 0;
}

.session-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.session-filter {
  margin-bottom: 14px;
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(29, 92, 99, 0.08);
}

.session-filter__label {
  font-size: 12px;
  color: var(--text-faint);
}

.session-filter__value {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--brand-strong);
}

.session-list {
  display: grid;
  gap: 10px;
  max-height: 680px;
  overflow: auto;
}

.session-item {
  display: grid;
  gap: 8px;
  width: 100%;
  padding: 14px;
  border-radius: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.9);
  text-align: left;
  cursor: pointer;
}

.session-item.is-active {
  border-color: rgba(29, 92, 99, 0.4);
  box-shadow: inset 0 0 0 1px rgba(29, 92, 99, 0.08);
  background: rgba(29, 92, 99, 0.06);
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
.session-item__count {
  font-size: 12px;
  color: var(--text-sub);
}

.agent-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.agent-header__actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.agent-panel {
  display: grid;
  grid-template-rows: 1fr auto;
  gap: 14px;
  min-height: 580px;
}

.chat-window {
  display: grid;
  gap: 12px;
  max-height: 640px;
  overflow: auto;
  padding: 12px;
  border-radius: 20px;
  border: 1px solid var(--line-soft);
  background: linear-gradient(180deg, rgba(245, 240, 232, 0.6), rgba(255, 255, 255, 0.78));
}

.chat-bubble {
  max-width: min(780px, 92%);
  padding: 14px 16px;
  border-radius: 18px;
  background: white;
  border: 1px solid var(--line-soft);
}

.chat-bubble.is-user {
  justify-self: end;
  background: rgba(29, 92, 99, 0.08);
}

.chat-bubble.is-assistant {
  justify-self: start;
}

.chat-bubble.is-system {
  justify-self: start;
  background: rgba(207, 122, 73, 0.08);
}

.chat-bubble__role {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-faint);
  text-transform: uppercase;
}

.chat-bubble__content {
  white-space: pre-wrap;
  line-height: 1.75;
}

.chat-compose {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  align-items: stretch;
}

@media (max-width: 1100px) {
  .agent-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .agent-header {
    flex-direction: column;
  }

  .chat-compose {
    grid-template-columns: 1fr;
  }
}
</style>
