<template>
  <div style="display: grid; gap: 12px">
    <el-card shadow="never" style="border-radius: 12px">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between">
          <div style="font-weight: 600">图谱展示（Neo4j）</div>
          <div style="display: flex; gap: 8px">
            <el-input v-model="docId" placeholder="可选：doc_id 过滤" style="max-width: 320px" />
            <el-button @click="loadGraph" :loading="graphLoading">刷新</el-button>
          </div>
        </div>
      </template>

      <div
        ref="graphEl"
        style="height: 460px; background: #fff; border-radius: 8px; border: 1px solid var(--el-border-color)"
      />
    </el-card>

    <el-card shadow="never" style="border-radius: 12px">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between">
          <div style="font-weight: 600">节点（Entities CRUD - Postgres）</div>
          <div style="display: flex; gap: 8px">
            <el-button type="primary" @click="openCreate">新增节点</el-button>
            <el-button @click="loadEntities" :loading="entitiesLoading">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table :data="entities" v-loading="entitiesLoading" row-key="entity_id" style="width: 100%">
        <el-table-column prop="entity_id" label="entity_id" width="280" />
        <el-table-column prop="canonical_name" label="canonical_name" />
        <el-table-column prop="type" label="type" width="120" />
        <el-table-column prop="doc_id" label="doc_id" width="240" />
        <el-table-column label="操作" width="200">
          <template #default="scope">
            <el-button size="small" @click="openEdit(scope.row)">编辑</el-button>
            <el-button size="small" type="danger" @click="remove(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" title="节点" width="680px">
      <el-form label-width="110px">
        <el-form-item label="entity_id">
          <el-input v-model="form.entity_id" placeholder="可选：不填则服务端生成" :disabled="editing" />
        </el-form-item>
        <el-form-item label="doc_id">
          <el-input v-model="form.doc_id" placeholder="必填：实体所属 doc_id" />
        </el-form-item>
        <el-form-item label="canonical_name">
          <el-input v-model="form.canonical_name" />
        </el-form-item>
        <el-form-item label="type">
          <el-input v-model="form.type" />
        </el-form-item>
        <el-form-item label="aliases">
          <el-input v-model="form.aliases" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="description">
          <el-input v-model="form.description" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { nextTick, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../lib/api'

import { Network } from 'vis-network'

const props = defineProps({
  groupId: { type: String, required: true },
})

const docId = ref('')

const graphLoading = ref(false)
const graphEl = ref(null)
let network = null

const entitiesLoading = ref(false)
const entities = ref([])

const dlg = ref(false)
const saving = ref(false)
const editing = ref(false)
const form = reactive({
  entity_id: '',
  doc_id: '',
  canonical_name: '',
  type: '',
  aliases: '',
  description: '',
})

function _graphToFlow(g) {
  const nodesIn = Array.isArray(g?.nodes) ? g.nodes : []
  const edgesIn = Array.isArray(g?.edges) ? g.edges : []

  const nameToId = new Map()
  const usedNodeIds = new Set()
  const ns = nodesIn.map((n, idx) => {
    const name = String(n?.name ?? n?.canonical_name ?? '').trim()
    const doc = String(n?.doc_id ?? '').trim()
    const rawId = String(n?.entity_id ?? n?.id ?? n?.node_id ?? '').trim()
    const baseId = rawId || (name ? `${doc || '_'}:${name}` : String(idx))
    let id = baseId
    let bump = 2
    while (usedNodeIds.has(id)) {
      id = `${baseId}#${bump}`
      bump += 1
    }
    usedNodeIds.add(id)
    if (name && !nameToId.has(name)) nameToId.set(name, id)
    const label = String(n?.label ?? (name || n?.canonical_name) ?? id)
    return {
      id,
      label,
      shape: 'dot',
      size: 14,
      font: { size: 12 },
    }
  })

  const usedEdgeIds = new Set()
  const es = edgesIn
    .map((e, idx) => {
      const headName = String(e?.head_name ?? '').trim()
      const tailName = String(e?.tail_name ?? '').trim()
      const from = String(e?.source ?? e?.from ?? e?.start ?? nameToId.get(headName) ?? headName ?? '').trim()
      const to = String(e?.target ?? e?.to ?? e?.end ?? nameToId.get(tailName) ?? tailName ?? '').trim()
      const label = String(e?.label ?? e?.type ?? '')
      const baseEdgeId = String(e?.id ?? e?.relation_id ?? `${from}-${to}-${idx}`)
      let id = baseEdgeId
      let bump = 2
      while (usedEdgeIds.has(id)) {
        id = `${baseEdgeId}#${bump}`
        bump += 1
      }
      usedEdgeIds.add(id)
      return {
        id,
        from,
        to,
        label,
        arrows: 'to',
        font: { align: 'middle', size: 10 },
      }
    })
    .filter((e) => e.from && e.to)

  return { ns, es }
}

async function _openEntityById(entityId) {
  const eid = String(entityId || '').trim()
  if (!eid) return

  try {
    const res = await api.get(`/entities/${encodeURIComponent(eid)}`, { params: { group_id: props.groupId } })
    if (!res.data) {
      ElMessage.warning('未找到对应实体（该节点可能来自 Neo4j，但不在 entities 表中）')
      return
    }
    openEdit(res.data)
  } catch (e) {
    ElMessage.warning('无法打开节点编辑（可能该节点不支持 CRUD）')
  }
}

function _ensureNetwork() {
  if (network || !graphEl.value) return
  network = new Network(
    graphEl.value,
    { nodes: [], edges: [] },
    {
      autoResize: true,
      interaction: { hover: true },
      physics: { stabilization: true },
    },
  )
  network.on('click', (params) => {
    const nodeId = params?.nodes?.[0]
    if (nodeId) _openEntityById(nodeId)
  })
}

async function loadGraph() {
  graphLoading.value = true
  try {
    const res = await api.get(`/groups/${encodeURIComponent(props.groupId)}/graph`, {
      params: { limit: 200, doc_id: docId.value.trim() || undefined },
    })
    const { ns, es } = _graphToFlow(res.data)

    await nextTick()
    _ensureNetwork()

    if (!ns.length) {
      ElMessage.warning('图谱为空：未返回任何节点（nodes=0）')
    } else {
      ElMessage.info(`图谱数据：nodes=${ns.length}, edges=${es.length}`)
    }

    if (network) {
      network.setData({ nodes: ns, edges: es })
      network.fit({ animation: { duration: 300 } })
    }
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '加载图谱失败'
    ElMessage.error(String(msg))
  } finally {
    graphLoading.value = false
  }
}

async function loadEntities() {
  entitiesLoading.value = true
  try {
    const res = await api.get('/entities', { params: { group_id: props.groupId, limit: 200 } })
    entities.value = Array.isArray(res.data) ? res.data : []
  } finally {
    entitiesLoading.value = false
  }
}

function openCreate() {
  editing.value = false
  form.entity_id = ''
  form.doc_id = ''
  form.canonical_name = ''
  form.type = ''
  form.aliases = ''
  form.description = ''
  dlg.value = true
}

function openEdit(row) {
  editing.value = true
  form.entity_id = row.entity_id
  form.doc_id = row.doc_id
  form.canonical_name = row.canonical_name
  form.type = row.type
  form.aliases = (row.aliases || []).join(',')
  form.description = row.description
  dlg.value = true
}

async function save() {
  const payload = {
    entity_id: editing.value ? undefined : ((form.entity_id || '').trim() || undefined),
    doc_id: (form.doc_id || '').trim(),
    canonical_name: (form.canonical_name || '').trim(),
    type: (form.type || '').trim(),
    aliases: (form.aliases || '').split(',').map((s) => s.trim()).filter(Boolean),
    description: form.description || '',
  }

  if (!payload.doc_id || !payload.canonical_name) {
    ElMessage.warning('doc_id / canonical_name 必填')
    return
  }

  saving.value = true
  try {
    if (editing.value) {
      await api.put(`/entities/${encodeURIComponent(form.entity_id)}`, payload, { params: { group_id: props.groupId } })
      ElMessage.success('已更新')
    } else {
      await api.post('/entities', payload, { params: { group_id: props.groupId } })
      ElMessage.success('已创建')
    }
    dlg.value = false
    await loadEntities()
    await loadGraph()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确认删除 entity_id=${row.entity_id} ?`, '删除确认', { type: 'warning' })
  await api.delete(`/entities/${encodeURIComponent(row.entity_id)}`, { params: { group_id: props.groupId } })
  ElMessage.success('已删除')
  await loadEntities()
  await loadGraph()
}

onMounted(async () => {
  await loadGraph()
  await loadEntities()
})

onBeforeUnmount(() => {
  try {
    network?.destroy()
  } catch {
    // ignore
  }
  network = null
})
</script>

