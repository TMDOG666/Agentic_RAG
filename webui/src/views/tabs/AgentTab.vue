<template>
  <div style="display: grid; gap: 12px">
    <el-card shadow="never" style="border-radius: 12px">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between">
          <div style="font-weight: 600">Agent 对话</div>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-select v-model="docId" clearable placeholder="可选：绑定 doc_id" style="width: 320px">
              <el-option v-for="d in docs" :key="d.doc_id" :label="`${d.doc_name} (${d.doc_id})`" :value="d.doc_id" />
            </el-select>
            <el-button @click="loadDocs" :loading="docsLoading">刷新文档</el-button>
          </div>
        </div>
      </template>

      <div style="display: grid; grid-template-rows: 1fr auto; height: 520px; gap: 10px">
        <div style="overflow: auto; padding: 10px; background: #fff; border: 1px solid var(--el-border-color); border-radius: 8px">
          <div v-for="(m, idx) in messages" :key="idx" style="margin-bottom: 10px">
            <div style="font-size: 12px; opacity: 0.7">{{ m.role }}</div>
            <div style="white-space: pre-wrap">{{ m.content }}</div>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr auto; gap: 8px">
          <el-input v-model="text" type="textarea" :rows="3" placeholder="输入问题，回车发送（或点发送）" @keydown.enter.exact.prevent="send" />
          <el-button type="primary" :loading="sending" @click="send" style="height: 100%">发送</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../lib/api'

const props = defineProps({
  groupId: { type: String, required: true },
})

const docsLoading = ref(false)
const docs = ref([])
const docId = ref('')

const messages = ref([
  { role: 'system', content: '你可以在这里与 Agent 对话。建议先选择 doc_id 或保持为空让其跨文档检索。' },
])

const text = ref('')
const sending = ref(false)

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

  messages.value.push({ role: 'user', content: t })
  text.value = ''

  sending.value = true
  try {
    const payload = {
      group_id: props.groupId,
      doc_id: docId.value || null,
      user_text: t,
    }
    const res = await api.post('/agent/run', payload)
    messages.value.push({ role: 'assistant', content: String(res.data?.reply || '') })
  } catch (e) {
    ElMessage.error(`请求失败: ${e?.message || e}`)
  } finally {
    sending.value = false
  }
}

onMounted(loadDocs)
</script>
