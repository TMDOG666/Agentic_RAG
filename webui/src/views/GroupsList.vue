<template>
  <el-card shadow="never" style="border-radius: 12px">
    <template #header>
      <div style="display: flex; align-items: center; justify-content: space-between">
        <div style="font-weight: 600">分组</div>
        <div>
          <el-button :loading="loading" @click="load" type="primary">刷新</el-button>
        </div>
      </div>
    </template>

    <el-table :data="groups" v-loading="loading" style="width: 100%" row-key="group_id">
      <el-table-column prop="group_id" label="group_id" />
      <el-table-column label="操作" width="160">
        <template #default="scope">
          <el-button size="small" type="primary" @click="go(scope.row.group_id)">进入</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../lib/api'

const router = useRouter()
const loading = ref(false)
const groups = ref([])

async function load() {
  loading.value = true
  try {
    const res = await api.get('/groups', { params: { limit: 500 } })
    groups.value = Array.isArray(res.data) ? res.data : []
  } finally {
    loading.value = false
  }
}

function go(groupId) {
  router.push(`/groups/${encodeURIComponent(groupId)}`)
}

onMounted(load)
</script>
