<template>
  <div class="page-grid">
    <section class="group-hero view-card">
      <div>
        <div class="eyebrow">Group Workspace</div>
        <h2>{{ groupId }}</h2>
        <p>在同一个视图里管理文档录入、后端日志、知识图谱和 Agent 问答。</p>
      </div>

      <div class="group-hero__actions">
        <el-button @click="back">返回分组列表</el-button>
      </div>
    </section>

    <el-card shadow="never" class="view-card">
      <el-tabs v-model="tab" class="detail-tabs">
        <el-tab-pane label="文档与日志" name="documents">
          <DocumentsTab :group-id="groupId" />
        </el-tab-pane>
        <el-tab-pane label="知识图谱" name="graph">
          <GraphTab :group-id="groupId" />
        </el-tab-pane>
        <el-tab-pane label="Agent 对话" name="agent">
          <AgentTab :group-id="groupId" />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import DocumentsTab from './tabs/DocumentsTab.vue'
import GraphTab from './tabs/GraphTab.vue'
import AgentTab from './tabs/AgentTab.vue'

defineProps({
  groupId: { type: String, required: true },
})

const router = useRouter()
const tab = ref('documents')

function back() {
  router.push('/')
}
</script>

<style scoped>
.group-hero {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  padding: 28px;
}

.group-hero h2 {
  margin: 10px 0 6px;
  font-size: 34px;
  color: var(--brand-strong);
}

.group-hero p {
  margin: 0;
  color: var(--text-sub);
}

.detail-tabs :deep(.el-tabs__header) {
  margin-bottom: 18px;
}

.detail-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.detail-tabs :deep(.el-tabs__item) {
  height: 42px;
  border-radius: 12px 12px 0 0;
  color: var(--text-sub);
}

.detail-tabs :deep(.el-tabs__item.is-active) {
  color: var(--brand-strong);
  font-weight: 700;
}

@media (max-width: 900px) {
  .group-hero {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
