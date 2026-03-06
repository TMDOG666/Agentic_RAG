import axios from 'axios'
import { ElMessage } from 'element-plus'

function getBaseUrl() {
  const env = import.meta?.env?.VITE_API_BASE_URL
  return (env || '').trim()
}

export const api = axios.create({
  baseURL: getBaseUrl() || '/api',
  timeout: 300000,
})

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    const msg = detail || error?.message || 'Request failed'
    if (status) {
      ElMessage.error(`${status}: ${msg}`)
    } else {
      ElMessage.error(String(msg))
    }
    return Promise.reject(error)
  },
)

export function getApiBaseUrlForDocs() {
  return getBaseUrl() || 'http://127.0.0.1:8080'
}
