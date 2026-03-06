<template>
  <el-card shadow="never" style="border-radius: 12px; overflow: hidden">
    <template #header>
      <div style="display: flex; align-items: center; justify-content: space-between">
        <div style="font-weight: 600">FastAPI /docs</div>
        <el-input v-model="baseUrl" style="max-width: 420px" placeholder="http://127.0.0.1:8080" />
      </div>
    </template>

    <div style="height: 80vh">
      <iframe :src="docsUrl" style="width: 100%; height: 100%; border: 0" />
    </div>
  </el-card>
</template>

<script setup>
import { computed, ref } from 'vue'

const baseUrl = ref((import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080').trim())

const docsUrl = computed(() => {
  const b = (baseUrl.value || '').trim().replace(/\/$/, '')
  return `${b}/docs`
})
</script>
