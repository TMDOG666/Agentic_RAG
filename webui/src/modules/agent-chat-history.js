const STORAGE_KEY = 'agentic-rag:agent-chat-history:v1'
const MAX_SESSIONS_PER_SCOPE = 20
const MAX_MESSAGES_PER_SESSION = 100

function safeParse(raw, fallback) {
  try {
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

function readStore() {
  if (typeof window === 'undefined') return {}
  return safeParse(window.localStorage.getItem(STORAGE_KEY) || '{}', {})
}

function writeStore(store) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
}

function buildScopeKey(groupId, docId) {
  return `${String(groupId || '').trim()}::${String(docId || '').trim() || '__group__'}`
}

function createDefaultMessages() {
  return [
    {
      role: 'system',
      content: '这里会保留当前会话的上下文。建议先选择文档，再发起更具体的问题。',
    },
  ]
}

function makeSession({ groupId, docId, firstUserMessage = '' }) {
  const title = String(firstUserMessage || '').trim().slice(0, 24) || '新会话'
  const now = new Date().toISOString()
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`,
    title,
    groupId: String(groupId || ''),
    docId: String(docId || ''),
    createdAt: now,
    updatedAt: now,
    messages: createDefaultMessages(),
  }
}

function normalizeSession(session) {
  const messages = Array.isArray(session?.messages) ? session.messages : createDefaultMessages()
  return {
    id: String(session?.id || ''),
    title: String(session?.title || '新会话'),
    groupId: String(session?.groupId || ''),
    docId: String(session?.docId || ''),
    createdAt: String(session?.createdAt || new Date().toISOString()),
    updatedAt: String(session?.updatedAt || new Date().toISOString()),
    messages: messages
      .filter((item) => item && typeof item.content === 'string' && typeof item.role === 'string')
      .slice(-MAX_MESSAGES_PER_SESSION),
  }
}

export function listSessions({ groupId, docId }) {
  const store = readStore()
  const scopeKey = buildScopeKey(groupId, docId)
  const sessions = Array.isArray(store[scopeKey]) ? store[scopeKey] : []
  return sessions.map(normalizeSession).sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)))
}

export function createSession({ groupId, docId, firstUserMessage = '' }) {
  const store = readStore()
  const scopeKey = buildScopeKey(groupId, docId)
  const sessions = listSessions({ groupId, docId })
  const session = makeSession({ groupId, docId, firstUserMessage })
  store[scopeKey] = [session, ...sessions].slice(0, MAX_SESSIONS_PER_SCOPE)
  writeStore(store)
  return session
}

export function upsertSession({ groupId, docId, session }) {
  const store = readStore()
  const scopeKey = buildScopeKey(groupId, docId)
  const current = listSessions({ groupId, docId }).filter((item) => item.id !== session.id)
  const normalized = normalizeSession({
    ...session,
    updatedAt: new Date().toISOString(),
    messages: Array.isArray(session?.messages) ? session.messages.slice(-MAX_MESSAGES_PER_SESSION) : createDefaultMessages(),
  })
  store[scopeKey] = [normalized, ...current].slice(0, MAX_SESSIONS_PER_SCOPE)
  writeStore(store)
  return normalized
}

export function deleteSession({ groupId, docId, sessionId }) {
  const store = readStore()
  const scopeKey = buildScopeKey(groupId, docId)
  const next = listSessions({ groupId, docId }).filter((item) => item.id !== sessionId)
  store[scopeKey] = next
  writeStore(store)
}

export function createEphemeralSession({ groupId, docId }) {
  return makeSession({ groupId, docId })
}
