<template>
  <div class="groups-page page-grid">
    <section class="groups-hero view-card">
      <div>
        <div class="eyebrow">Collections</div>
        <h2>把知识库按业务分组，清晰管理每条入库链路。</h2>
        <p>
          这里集中展示所有分组入口。进入分组后，可以继续处理文档录入、日志追踪、图谱查看和 Agent 对话。
        </p>
      </div>

      <div class="groups-hero__stats">
        <div class="stat-card">
          <span>分组数量</span>
          <strong>{{ groups.length }}</strong>
        </div>
        <div class="stat-card">
          <span>状态</span>
          <strong>{{ loading ? '加载中' : '已同步' }}</strong>
        </div>
      </div>
    </section>

    <el-card shadow="never" class="view-card">
      <template #header>
        <div class="header-row">
          <div>
            <div class="section-title">分组列表</div>
            <div class="section-subtitle">支持创建、编辑、删除和进入分组工作台。</div>
          </div>
          <div class="header-actions">
            <el-button @click="openCreate" type="primary">新建分组</el-button>
            <el-button :loading="loading" @click="load">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table :data="groups" v-loading="loading" row-key="group_id" class="shell-table" empty-text="还没有任何分组">
        <el-table-column prop="group_id" label="Group ID" min-width="180">
          <template #default="scope">
            <div class="group-id mono">{{ scope.row.group_id }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="group_name" label="名称" min-width="180" />
        <el-table-column prop="group_desc" label="描述" min-width="280" />
        <el-table-column label="操作" width="180">
          <template #default="scope">
            <div class="table-actions">
              <el-button size="small" type="primary" @click="go(scope.row.group_id)">进入</el-button>
              <el-dropdown @command="(cmd) => onRowCmd(cmd, scope.row)">
                <el-button size="small">更多</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="edit">编辑</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>

  <el-dialog v-model="dlg" :title="editing ? '编辑分组' : '新建分组'" width="640px" append-to-body align-center>
    <el-form label-width="90px">
      <el-form-item label="group_id">
        <el-input v-model="form.group_id" :disabled="editing" placeholder="例如：report_group" class="glass-input" />
      </el-form-item>
      <el-form-item label="名称">
        <el-input v-model="form.group_name" placeholder="给分组一个更好识别的名字" class="glass-input" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.group_desc" type="textarea" :rows="3" placeholder="说明这个分组的用途" class="glass-input" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dlg = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../lib/api'

const router = useRouter()
const loading = ref(false)
const groups = ref([])

const dlg = ref(false)
const saving = ref(false)
const editing = ref(false)
const form = reactive({
  group_id: '',
  group_name: '',
  group_desc: '',
})

async function load() {
  loading.value = true
  try {
    try {
      const res = await api.get('/groups-admin', { params: { limit: 500 } })
      groups.value = Array.isArray(res.data) ? res.data : []
    } catch {
      const res = await api.get('/groups', { params: { limit: 500 } })
      const arr = Array.isArray(res.data) ? res.data : []
      groups.value = arr.map((g) => ({ group_id: g.group_id, group_name: '', group_desc: '' }))
    }
  } finally {
    loading.value = false
  }
}

function go(groupId) {
  router.push(`/groups/${encodeURIComponent(groupId)}`)
}

function openCreate() {
  editing.value = false
  form.group_id = ''
  form.group_name = ''
  form.group_desc = ''
  dlg.value = true
}

function openEdit(row) {
  editing.value = true
  form.group_id = row.group_id
  form.group_name = row.group_name || ''
  form.group_desc = row.group_desc || ''
  dlg.value = true
}

async function save() {
  const groupId = String(form.group_id || '').trim()
  if (!groupId) {
    ElMessage.warning('group_id 必填')
    return
  }
  saving.value = true
  try {
    await api.post('/groups-admin', {
      group_id: groupId,
      group_name: String(form.group_name || ''),
      group_desc: String(form.group_desc || ''),
    })
    ElMessage.success(editing.value ? '分组已更新' : '分组已创建')
    dlg.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  const gid = String(row?.group_id || '').trim()
  if (!gid) return
  const { value } = await ElMessageBox.prompt(
    `删除会级联清理该分组下所有文档、向量和图数据。请输入 group_id 确认：`,
    '删除确认',
    {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      inputPlaceholder: gid,
    },
  )
  if (String(value || '').trim() !== gid) {
    ElMessage.warning('输入不匹配，已取消删除')
    return
  }
  await api.delete(`/groups-admin/${encodeURIComponent(gid)}`)
  ElMessage.success('分组已删除')
  await load()
}

function onRowCmd(cmd, row) {
  if (cmd === 'edit') openEdit(row)
  if (cmd === 'delete') remove(row)
}

onMounted(load)
</script>

<style scoped>
.groups-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(220px, 0.8fr);
  gap: 18px;
  padding: 28px;
}

.groups-hero h2 {
  margin: 10px 0;
  font-size: 30px;
  line-height: 1.18;
  color: var(--brand-strong);
}

.groups-hero p {
  margin: 0;
  max-width: 700px;
  line-height: 1.75;
  color: var(--text-sub);
}

.groups-hero__stats {
  display: grid;
  gap: 12px;
}

.stat-card {
  padding: 18px 20px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(29, 92, 99, 0.1), rgba(29, 92, 99, 0.04));
}

.stat-card span {
  display: block;
  font-size: 12px;
  color: var(--text-sub);
}

.stat-card strong {
  display: block;
  margin-top: 8px;
  font-size: 28px;
  color: var(--brand-strong);
}

.header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.group-id {
  font-size: 12px;
  color: var(--text-sub);
}

@media (max-width: 900px) {
  .groups-hero {
    grid-template-columns: 1fr;
  }
}
</style>
