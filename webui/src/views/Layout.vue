<template>
  <div class="layout-shell">
    <div class="layout-frame app-shell-card">
      <aside class="layout-sidebar">
        <div class="brand-block">
          <div class="eyebrow">Agentic RAG</div>
          <h1>知识工作台</h1>
          <p>围绕分组、文档、图谱和 Agent 的统一操作入口。</p>
        </div>

        <el-menu :default-active="active" router class="side-menu">
          <el-menu-item index="/">
            <span>分组总览</span>
          </el-menu-item>
          <el-menu-item index="/api-docs">
            <span>接口文档</span>
          </el-menu-item>
        </el-menu>

        <div class="sidebar-tip">
          <div class="sidebar-tip__label">当前页面</div>
          <div class="sidebar-tip__value">{{ title }}</div>
          <div class="sidebar-tip__text">如果页面内容没刷新，优先检查后端服务和 `VITE_API_BASE_URL`。</div>
        </div>
      </aside>

      <main class="layout-main">
        <header class="layout-header">
          <div>
            <div class="eyebrow">Workspace</div>
            <div class="layout-header__title">{{ title }}</div>
            <el-breadcrumb separator="/" class="layout-breadcrumb">
              <el-breadcrumb-item to="/">分组</el-breadcrumb-item>
              <el-breadcrumb-item v-if="route.name === 'group'">{{ route.params.groupId }}</el-breadcrumb-item>
              <el-breadcrumb-item v-if="route.name === 'api-docs'">API Docs</el-breadcrumb-item>
            </el-breadcrumb>
          </div>

          <div class="layout-header__meta">
            <div class="layout-chip">
              <span class="layout-chip__dot" />
              <span>WebUI</span>
            </div>
          </div>
        </header>

        <section class="layout-content">
          <router-view />
        </section>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const active = computed(() => route.path)

const title = computed(() => {
  if (route.name === 'groups') return '分组列表'
  if (route.name === 'group') return `分组：${route.params.groupId}`
  if (route.name === 'api-docs') return 'FastAPI 接口文档'
  return 'Agentic RAG'
})
</script>

<style scoped>
.layout-shell {
  min-height: 100vh;
  padding: 20px;
}

.layout-frame {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: calc(100vh - 40px);
  overflow: hidden;
}

.layout-sidebar {
  display: grid;
  grid-template-rows: auto auto 1fr;
  gap: 22px;
  padding: 28px 24px;
  border-right: 1px solid rgba(19, 61, 71, 0.08);
  background:
    radial-gradient(circle at top left, rgba(207, 122, 73, 0.16), transparent 24%),
    linear-gradient(180deg, rgba(249, 245, 236, 0.96), rgba(245, 248, 250, 0.92));
}

.brand-block h1 {
  margin: 10px 0 8px;
  font-size: 30px;
  line-height: 1.1;
  color: var(--brand-strong);
}

.brand-block p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-sub);
}

.side-menu {
  border-right: 0;
  background: transparent;
}

.side-menu :deep(.el-menu-item) {
  margin-bottom: 6px;
  border-radius: 14px;
  color: var(--text-main);
}

.side-menu :deep(.el-menu-item.is-active) {
  background: rgba(29, 92, 99, 0.12);
  color: var(--brand-strong);
}

.sidebar-tip {
  align-self: end;
  padding: 18px;
  border-radius: 20px;
  background: rgba(19, 61, 71, 0.92);
  color: rgba(245, 247, 249, 0.92);
}

.sidebar-tip__label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  opacity: 0.72;
}

.sidebar-tip__value {
  margin-top: 10px;
  font-size: 20px;
  font-weight: 700;
}

.sidebar-tip__text {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.7;
  opacity: 0.8;
}

.layout-main {
  display: grid;
  grid-template-rows: auto 1fr;
  min-width: 0;
}

.layout-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 24px 30px 18px;
  border-bottom: 1px solid rgba(19, 61, 71, 0.08);
}

.layout-header__title {
  margin-top: 10px;
  font-size: 28px;
  font-weight: 700;
  color: var(--brand-strong);
}

.layout-breadcrumb {
  margin-top: 10px;
}

.layout-header__meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.layout-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(29, 92, 99, 0.08);
  color: var(--brand-strong);
  font-size: 13px;
  font-weight: 600;
}

.layout-chip__dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--success);
}

.layout-content {
  min-width: 0;
  padding: 24px 30px 30px;
}

@media (max-width: 1100px) {
  .layout-shell {
    padding: 0;
  }

  .layout-frame {
    grid-template-columns: 1fr;
    min-height: 100vh;
  }

  .layout-sidebar {
    border-right: 0;
    border-bottom: 1px solid rgba(19, 61, 71, 0.08);
  }
}
</style>
