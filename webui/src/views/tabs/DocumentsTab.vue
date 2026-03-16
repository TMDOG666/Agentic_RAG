<template>
  <div style="display: grid; gap: 12px">
    <el-card shadow="never" style="border-radius: 12px">
      <div style="display: flex; gap: 8px; align-items: center; justify-content: space-between">
        <div style="font-weight: 600">文档列表</div>
        <div style="display: flex; gap: 8px">
          <el-button @click="openUpload" type="success">上传文件</el-button>
          <el-button @click="openCreate" type="primary">新增/重建</el-button>
          <el-button @click="load" :loading="loading">刷新</el-button>
        </div>
      </div>

      <el-table :data="docs" v-loading="loading" style="width: 100%; margin-top: 12px" row-key="doc_id">
        <el-table-column prop="doc_id" label="doc_id" width="280" />
        <el-table-column prop="doc_name" label="doc_name" />
        <el-table-column prop="doc_time" label="doc_time" width="200" />
        <el-table-column label="操作" width="160">
          <template #default="scope">
            <el-button size="small" @click="openReingest(scope.row)">重建</el-button>
            <el-button size="small" type="danger" @click="remove(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" title="新增/重建文档" width="720px">
      <el-form label-width="90px">
        <el-form-item label="doc_id">
          <el-input v-model="form.doc_id" placeholder="可选：不填则创建新文档；填则尝试用该 doc_id 重建" />
        </el-form-item>
        <el-form-item label="doc_name">
          <el-input v-model="form.doc_name" placeholder="例如 report.txt" />
        </el-form-item>
        <el-form-item label="doc_time">
          <el-input v-model="form.doc_time" placeholder="建议 ISO8601，例如 2026-03-05T07:12:34Z" />
        </el-form-item>
        <el-form-item label="text">
          <el-input v-model="form.text" type="textarea" :rows="10" placeholder="要入库的纯文本" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="uploadDlg" title="上传文件并入库" width="720px">
      <el-form label-width="90px">
        <el-form-item label="文档ID">
          <el-input v-model="uploadForm.doc_id" placeholder="可选：不填则创建新文档；填则尝试用该文档ID重建" />
        </el-form-item>
        <el-form-item label="文档时间">
          <el-date-picker
            v-model="uploadForm.doc_time"
            type="datetime"
            placeholder="请选择时间"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="标准化">
          <el-switch v-model="uploadForm.standardize" />
        </el-form-item>
        <el-form-item label="文件">
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            :on-change="onUploadChange"
            :on-remove="onUploadRemove"
            :show-file-list="true"
            style="width: 100%"
          >
            <div style="padding: 14px 0">
              <div style="font-weight: 600">拖拽文件到此处</div>
              <div style="font-size: 12px; opacity: 0.75; margin-top: 6px">或点击选择文件</div>
            </div>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDlg=false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="upload">上传</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../lib/api'

const props = defineProps({
  groupId: { type: String, required: true },
})

const loading = ref(false)
const saving = ref(false)
const docs = ref([])

const dlg = ref(false)
const uploadDlg = ref(false)
const form = reactive({
  doc_id: '',
  doc_name: '',
  doc_time: '',
  text: '',
})

const uploading = ref(false)
const uploadForm = reactive({
  doc_id: '',
  doc_time: null,
  standardize: true,
  file: null,
  filename: '',
})

async function load() {
  loading.value = true
  try {
    const res = await api.get(`/groups/${encodeURIComponent(props.groupId)}/documents`, { params: { limit: 200 } })
    docs.value = Array.isArray(res.data) ? res.data : []
  } finally {
    loading.value = false
  }

}

function openUpload() {
  uploadForm.doc_id = ''
  uploadForm.doc_time = null
  uploadForm.standardize = true
  uploadForm.file = null
  uploadForm.filename = ''
  uploadDlg.value = true
}

function onUploadChange(uploadFile) {
  const raw = uploadFile?.raw
  uploadForm.file = raw || null
  uploadForm.filename = raw?.name || uploadFile?.name || ''
}

function onUploadRemove() {
  uploadForm.file = null
  uploadForm.filename = ''
}

async function upload() {
  if (!uploadForm.file) {
    ElMessage.warning('请选择文件')
    return
  }
  if (!uploadForm.doc_time) {
    ElMessage.warning('文档时间不能为空')
    return
  }

  let docTimeIso = ''
  try {
    docTimeIso = new Date(uploadForm.doc_time).toISOString()
  } catch {
    docTimeIso = ''
  }
  if (!docTimeIso) {
    ElMessage.warning('文档时间格式不合法')
    return
  }

  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', uploadForm.file)

    const params = {
      group_id: props.groupId,
      doc_time: docTimeIso,
      doc_id: String(uploadForm.doc_id || '').trim() || undefined,
      standardize: Boolean(uploadForm.standardize),
    }

    const res = await api.post('/ingest/upload', fd, {
      params,
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    ElMessage.success(`已上传：doc_id=${res.data?.doc_id || ''}`)
    uploadDlg.value = false
    await load()
  } finally {
    uploading.value = false
  }
}

function openCreate() {
  form.doc_id = ''
  form.doc_name = ''
  form.doc_time = ''
  form.text = ''
  dlg.value = true
}

function openReingest(row) {
  form.doc_id = row.doc_id
  form.doc_name = row.doc_name
  form.doc_time = row.doc_time
  form.text = ''
  dlg.value = true
}

async function save() {
  saving.value = true
  try {
    const payload = {
      group_id: props.groupId,
      doc_id: (form.doc_id || '').trim() || null,
      doc_name: (form.doc_name || '').trim(),
      doc_time: (form.doc_time || '').trim(),
      text: form.text || '',
    }
    if (!payload.doc_name || !payload.doc_time || !payload.text) {
      ElMessage.warning('doc_name/doc_time/text 不能为空')
      return
    }
    const res = await api.post('/ingest/text', payload)
    ElMessage.success(`已提交：doc_id=${res.data?.doc_id || ''}`)
    dlg.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确认删除 doc_id=${row.doc_id} ?`, '删除确认', { type: 'warning' })
  await api.delete(`/documents/${encodeURIComponent(row.doc_id)}`, { params: { group_id: props.groupId } })
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>
