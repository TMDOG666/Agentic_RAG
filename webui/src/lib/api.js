import axios from 'axios'
import { ElMessage } from 'element-plus'

function getBaseUrl() {
  const env = import.meta?.env?.VITE_API_BASE_URL
  return (env || '').trim()
}

export const api = axios.create({
  baseURL: getBaseUrl() || '/api',
  timeout: 300000,
})

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    const msg = detail || error?.message || 'Request failed'
    if (status) {
      ElMessage.error(`${status}: ${msg}`)
    } else {
      ElMessage.error(String(msg))
    }
    return Promise.reject(error)
  },
)

export function getApiBaseUrlForDocs() {
  return getBaseUrl() || 'http://127.0.0.1:8080'
}

export function getResolvedApiBaseUrl() {
  const base = getBaseUrl() || '/api'
  if (/^https?:\/\//i.test(base)) return base
  return `${window.location.origin}${base.startsWith('/') ? '' : '/'}${base}`
}

export async function postEventStream(path, payload, handlers = {}) {
  const response = await fetch(`${getResolvedApiBaseUrl()}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  if (!response.ok || !response.body) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const emitBlock = (block) => {
    const lines = block.split('\n')
    let event = 'message'
    const dataLines = []
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!dataLines.length) return
    let payloadData = dataLines.join('\n')
    try {
      payloadData = JSON.parse(payloadData)
    } catch {
      // keep raw text
    }
    handlers.onEvent?.(event, payloadData)
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

    let splitIndex = buffer.indexOf('\n\n')
    while (splitIndex >= 0) {
      const block = buffer.slice(0, splitIndex).trim()
      buffer = buffer.slice(splitIndex + 2)
      if (block) emitBlock(block)
      splitIndex = buffer.indexOf('\n\n')
    }

    if (done) break
  }

  if (buffer.trim()) emitBlock(buffer.trim())
}
