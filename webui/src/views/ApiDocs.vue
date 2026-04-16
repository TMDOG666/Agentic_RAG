<template>
  <div class="page-grid">
    <section class="docs-hero view-card">
      <div>
        <div class="eyebrow">Developer Surface</div>
        <h2>直接在工作台内查看后端接口文档。</h2>
        <p>如果你把 API 服务部署到其他地址，可以在这里临时切换文档入口，不需要改前端配置。</p>
      </div>
    </section>

    <el-card shadow="never" class="view-card docs-card">
      <template #header>
        <div class="docs-header">
          <div>
            <div class="section-title">FastAPI /docs</div>
            <div class="section-subtitle">默认指向本地 API 服务，也支持临时切换到其他环境。</div>
          </div>
          <el-input v-model="baseUrl" class="glass-input" style="max-width: 420px" placeholder="http://127.0.0.1:8080" />
        </div>
      </template>

      <div class="docs-frame">
        <iframe :src="docsUrl" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const baseUrl = ref((import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080').trim())

const docsUrl = computed(() => {
  const b = (baseUrl.value || '').trim().replace(/\/$/, '')
  return `${b}/docs`
})
</script>

<style scoped>
.docs-hero {
  padding: 28px;
}

.docs-hero h2 {
  margin: 10px 0 8px;
  font-size: 30px;
  color: var(--brand-strong);
}

.docs-hero p {
  margin: 0;
  color: var(--text-sub);
}

.docs-card {
  overflow: hidden;
}

.docs-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.docs-frame {
  height: 76vh;
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid var(--line-soft);
}

.docs-frame iframe {
  width: 100%;
  height: 100%;
  border: 0;
  background: white;
}

@media (max-width: 900px) {
  .docs-header {
    flex-direction: column;
  }
}
</style>
