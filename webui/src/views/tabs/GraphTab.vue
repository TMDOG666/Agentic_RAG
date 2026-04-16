<template>
  <div class="page-grid">
    <el-card shadow="never" class="view-card">
      <template #header>
        <div class="graph-header">
          <div>
            <div class="section-title">图谱视图</div>
            <div class="section-subtitle">优先展示当前分组图谱，也支持按 `doc_id` 单文档过滤。</div>
          </div>
          <div class="graph-header__actions">
            <el-input v-model="docId" placeholder="可选：doc_id 过滤" class="glass-input" style="max-width: 320px" />
            <el-button @click="loadGraph" :loading="graphLoading">刷新图谱</el-button>
          </div>
        </div>
      </template>

      <div class="graph-stage">
        <div ref="graphEl" class="graph-canvas" />
        <div class="graph-hint">
          <span>点击图节点可尝试打开对应实体。</span>
          <span v-if="graphSummary">{{ graphSummary }}</span>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="view-card">
      <template #header>
        <div class="graph-header">
          <div>
            <div class="section-title">实体列表</div>
            <div class="section-subtitle">这里是 Postgres 中可编辑的实体资产，和 Neo4j 图谱相互配合。</div>
          </div>
          <div class="graph-header__actions">
            <el-button type="primary" @click="openCreate">新增实体</el-button>
            <el-button @click="loadEntities" :loading="entitiesLoading">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table :data="entities" v-loading="entitiesLoading" row-key="entity_id" class="shell-table" empty-text="暂无实体">
        <el-table-column prop="canonical_name" label="名称" min-width="180" />
        <el-table-column prop="type" label="类型" width="120" />
        <el-table-column prop="doc_id" label="Doc ID" min-width="200" />
        <el-table-column prop="entity_id" label="Entity ID" min-width="260">
          <template #default="scope">
            <span class="mono entity-id">{{ scope.row.entity_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="scope">
            <div class="table-actions">
              <el-button size="small" @click="openEdit(scope.row)">编辑</el-button>
              <el-button size="small" type="danger" @click="remove(scope.row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" :title="editing ? '编辑实体' : '新增实体'" width="680px" append-to-body align-center>
      <el-form label-width="110px">
        <el-form-item label="entity_id">
          <el-input v-model="form.entity_id" :disabled="editing" placeholder="留空则由服务端生成" class="glass-input" />
        </el-form-item>
        <el-form-item label="doc_id">
          <el-input v-model="form.doc_id" placeholder="实体所属 doc_id" class="glass-input" />
        </el-form-item>
        <el-form-item label="canonical_name">
          <el-input v-model="form.canonical_name" class="glass-input" />
        </el-form-item>
        <el-form-item label="type">
          <el-input v-model="form.type" class="glass-input" />
        </el-form-item>
        <el-form-item label="aliases">
          <el-input v-model="form.aliases" placeholder="逗号分隔" class="glass-input" />
        </el-form-item>
        <el-form-item label="description">
          <el-input v-model="form.description" type="textarea" :rows="4" class="glass-input" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../lib/api'
import { Network } from 'vis-network'

const props = defineProps({
  groupId: { type: String, required: true },
})

const docId = ref('')
const graphLoading = ref(false)
const graphEl = ref(null)
const graphSummary = ref('')
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

function graphToFlow(g) {
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

    return {
      id,
      label: String(n?.label ?? name ?? id),
      shape: 'dot',
      size: 16,
      color: {
        background: '#f3e6d8',
        border: '#1d5c63',
        highlight: { background: '#ffd5b8', border: '#a35b32' },
      },
      font: { color: '#1f2a33', size: 13, face: 'Segoe UI', strokeWidth: 0 },
    }
  })

  const usedEdgeIds = new Set()
  const es = edgesIn
    .map((e, idx) => {
      const headName = String(e?.head_name ?? '').trim()
      const tailName = String(e?.tail_name ?? '').trim()
      const from = String(e?.source ?? e?.from ?? e?.start ?? nameToId.get(headName) ?? headName ?? '').trim()
      const to = String(e?.target ?? e?.to ?? e?.end ?? nameToId.get(tailName) ?? tailName ?? '').trim()
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
        label: String(e?.label ?? e?.type ?? ''),
        arrows: 'to',
        color: { color: '#7b8f99', highlight: '#cf7a49' },
        font: { align: 'middle', size: 10, color: '#4e5d68' },
        smooth: { type: 'dynamic' },
      }
    })
    .filter((e) => e.from && e.to)

  return { ns, es }
}

async function openEntityById(entityId) {
  const eid = String(entityId || '').trim()
  if (!eid) return
  try {
    const res = await api.get(`/entities/${encodeURIComponent(eid)}`, { params: { group_id: props.groupId } })
    if (!res.data) {
      ElMessage.warning('没有找到对应实体，可能该节点仅存在于图数据库中。')
      return
    }
    openEdit(res.data)
  } catch {
    ElMessage.warning('该节点当前不支持直接编辑。')
  }
}

function ensureNetwork() {
  if (network || !graphEl.value) return
  network = new Network(
    graphEl.value,
    { nodes: [], edges: [] },
    {
      autoResize: true,
      interaction: { hover: true },
      physics: { stabilization: true, barnesHut: { springLength: 160 } },
    },
  )
  network.on('click', (params) => {
    const nodeId = params?.nodes?.[0]
    if (nodeId) openEntityById(nodeId)
  })
}

async function loadGraph() {
  graphLoading.value = true
  try {
    const res = await api.get(`/groups/${encodeURIComponent(props.groupId)}/graph`, {
      params: { limit: 200, doc_id: docId.value.trim() || undefined },
    })
    const { ns, es } = graphToFlow(res.data)
    graphSummary.value = ns.length ? `nodes=${ns.length}，edges=${es.length}` : '当前没有返回图谱数据'

    await nextTick()
    ensureNetwork()
    if (network) {
      network.setData({ nodes: ns, edges: es })
      if (ns.length) {
        network.fit({ animation: { duration: 300 } })
      }
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
    ElMessage.warning('doc_id 和 canonical_name 必填')
    return
  }

  saving.value = true
  try {
    if (editing.value) {
      await api.put(`/entities/${encodeURIComponent(form.entity_id)}`, payload, { params: { group_id: props.groupId } })
      ElMessage.success('实体已更新')
    } else {
      await api.post('/entities', payload, { params: { group_id: props.groupId } })
      ElMessage.success('实体已创建')
    }
    dlg.value = false
    await loadEntities()
    await loadGraph()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确认删除 entity_id=${row.entity_id} ？`, '删除确认', { type: 'warning' })
  await api.delete(`/entities/${encodeURIComponent(row.entity_id)}`, { params: { group_id: props.groupId } })
  ElMessage.success('实体已删除')
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

<style scoped>
.graph-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.graph-header__actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.graph-stage {
  display: grid;
  gap: 12px;
}

.graph-canvas {
  height: 520px;
  border-radius: 20px;
  border: 1px solid var(--line-soft);
  background:
    radial-gradient(circle at top left, rgba(29, 92, 99, 0.1), transparent 18%),
    linear-gradient(180deg, #fbfaf7, #f4f7f9);
}

.graph-hint {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-sub);
}

.entity-id {
  font-size: 12px;
  color: var(--text-sub);
}

@media (max-width: 900px) {
  .graph-header {
    flex-direction: column;
  }
}
</style>
