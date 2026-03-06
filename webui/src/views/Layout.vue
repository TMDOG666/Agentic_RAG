<template>
  <el-container style="min-height: 100vh">
    <el-aside width="240px" style="border-right: 1px solid var(--el-border-color)">
      <div style="padding: 16px; font-weight: 700; font-size: 16px">Agentic RAG</div>
      <el-menu :default-active="active" router style="border-right: 0">
        <el-menu-item index="/">分组</el-menu-item>
        <el-menu-item index="/api-docs">API Docs</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--el-border-color)">
        <div style="display: flex; flex-direction: column; gap: 6px">
          <div style="font-weight: 600">{{ title }}</div>
          <el-breadcrumb separator="/" style="font-size: 12px">
            <el-breadcrumb-item to="/">分组</el-breadcrumb-item>
            <el-breadcrumb-item v-if="route.name === 'group'">{{ route.params.groupId }}</el-breadcrumb-item>
            <el-breadcrumb-item v-if="route.name === 'api-docs'">API Docs</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div style="display: flex; gap: 10px; align-items: center">
          <el-switch v-model="dark" active-text="暗色" inactive-text="亮色" />
          <div style="opacity: 0.75; font-size: 12px">WebUI</div>
        </div>
      </el-header>
      <el-main style="background: #f6f8fb">
        <div style="max-width: 1200px; margin: 0 auto">
          <router-view />
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, watchEffect } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const dark = computed({
  get() {
    return document.documentElement.classList.contains('dark')
  },
  set(v) {
    document.documentElement.classList.toggle('dark', Boolean(v))
  },
})

watchEffect(() => {
  document.body.style.background = dark.value ? '#0b0f19' : '#f6f8fb'
})

const active = computed(() => route.path)

const title = computed(() => {
  if (route.name === 'groups') return '分组列表'
  if (route.name === 'group') return `分组：${route.params.groupId}`
  if (route.name === 'api-docs') return 'FastAPI 文档'
  return 'Agentic RAG'
})
</script>
