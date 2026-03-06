<template>
  <el-card shadow="never" style="border-radius: 12px">
    <template #header>
      <div style="display: flex; align-items: center; justify-content: space-between">
        <div style="font-weight: 600">分组：{{ groupId }}</div>
        <el-button @click="back">返回</el-button>
      </div>
    </template>

    <el-tabs v-model="tab" type="border-card">
      <el-tab-pane label="文档" name="documents">
        <DocumentsTab :group-id="groupId" />
      </el-tab-pane>
      <el-tab-pane label="知识图谱" name="graph">
        <GraphTab :group-id="groupId" />
      </el-tab-pane>
      <el-tab-pane label="Agent" name="agent">
        <AgentTab :group-id="groupId" />
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import DocumentsTab from './tabs/DocumentsTab.vue'
import GraphTab from './tabs/GraphTab.vue'
import AgentTab from './tabs/AgentTab.vue'

const props = defineProps({
  groupId: { type: String, required: true },
})

const router = useRouter()
const tab = ref('documents')

function back() {
  router.push('/')
}
</script>
