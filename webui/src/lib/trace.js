export function normalizeTraceStatus(status) {
  const value = String(status || '').trim().toLowerCase()
  if (!value) return 'pending'
  if (['done', 'completed', 'success', 'succeeded'].includes(value)) return 'completed'
  if (['error', 'failed'].includes(value)) return 'failed'
  if (['running', 'processing', 'active', 'in_progress', 'recovering'].includes(value)) return 'running'
  if (['queued', 'waiting'].includes(value)) return 'pending'
  return value
}

export function normalizeTraceUsage(payload = {}) {
  return {
    inputTokens: Number(payload.input_tokens ?? payload.inputTokens ?? 0) || 0,
    outputTokens: Number(payload.output_tokens ?? payload.outputTokens ?? 0) || 0,
    totalTokens: Number(payload.total_tokens ?? payload.totalTokens ?? 0) || 0,
    isEstimated: Boolean(payload.is_estimated ?? payload.isEstimated),
    latencyMs: Number(payload.latency_ms ?? payload.latencyMs ?? 0) || 0,
  }
}

export function normalizeTraceStep(step = {}) {
  const payload = step?.payload && typeof step.payload === 'object' ? step.payload : {}
  return {
    ...step,
    step_id: step.step_id || `${Date.now()}-${Math.random().toString(16).slice(2, 6)}`,
    source: step.source || 'system',
    kind: step.kind || 'system',
    event: step.event || 'trace',
    step_name: step.step_name || step.title || step.event || 'trace',
    title: step.title || step.step_name || step.event || 'trace',
    status: normalizeTraceStatus(step.status),
    started_at: step.started_at || step.updated_at || '',
    ended_at: step.ended_at || '',
    updated_at: step.updated_at || step.ended_at || step.started_at || new Date().toISOString(),
    latency_ms: Number(step.latency_ms || 0) || 0,
    tokens: normalizeTraceUsage(step.tokens || {}),
    error: step.error || null,
    payload,
  }
}

export function sortTraceSteps(steps = []) {
  return [...steps]
    .map(normalizeTraceStep)
    .sort((a, b) => {
      const timeA = new Date(a.updated_at || a.started_at || 0).getTime()
      const timeB = new Date(b.updated_at || b.started_at || 0).getTime()
      if (timeA !== timeB) return timeA - timeB
      return String(a.step_id || '').localeCompare(String(b.step_id || ''))
    })
}
