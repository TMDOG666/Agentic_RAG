<template>
  <el-card shadow="never" style="border-radius: 12px">
    <template #header>
      <div style="display: flex; align-items: center; justify-content: space-between">
        <div style="font-weight: 600">分组</div>
        <div>
          <el-button @click="openCreate" type="primary">新增</el-button>
          <el-button :loading="loading" @click="load" type="primary">刷新</el-button>
        </div>
      </div>
    </template>

    <el-table :data="groups" v-loading="loading" style="width: 100%" row-key="group_id">
      <el-table-column prop="group_id" label="group_id" />
      <el-table-column prop="group_name" label="名称" min-width="160" />
      <el-table-column prop="group_desc" label="描述" min-width="220" />
      <el-table-column label="操作" width="160">
        <template #default="scope">
          <el-button size="small" type="primary" @click="go(scope.row.group_id)">进入</el-button>
          <el-dropdown style="margin-left: 8px" @command="(cmd) => onRowCmd(cmd, scope.row)">
            <el-button size="small">更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit">编辑</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="dlg" :title="editing ? '编辑分组' : '新增分组'" width="640px">
    <el-form label-width="90px">
      <el-form-item label="group_id">
        <el-input v-model="form.group_id" :disabled="editing" placeholder="例如：demo_group" />
      </el-form-item>
      <el-form-item label="名称">
        <el-input v-model="form.group_name" placeholder="可选" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.group_desc" type="textarea" :rows="3" placeholder="可选" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dlg=false">取消</el-button>
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
    ElMessage.success(editing.value ? '已保存' : '已创建')
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
    `删除会级联清理该组下所有文档与向量/图数据。\n请输入 group_id 以确认删除：`,
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
  ElMessage.success('已删除')
  await load()
}

function onRowCmd(cmd, row) {
  if (cmd === 'edit') openEdit(row)
  if (cmd === 'delete') remove(row)
}

onMounted(load)
</script>
