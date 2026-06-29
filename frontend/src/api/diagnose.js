import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

/**
 * 诊断请求（同步，保留兼容）
 */
export async function diagnose(query, sessionId = null) {
  const data = { query }
  if (sessionId) {
    data.session_id = sessionId
  }
  const response = await api.post('/diagnose', data)
  return response.data
}

/**
 * SSE 流式诊断请求
 * @param {string} query - 用户问题
 * @param {string|null} sessionId - 会话ID
 * @param {Object} callbacks - 回调函数
 * @param {function} callbacks.onStatus - 状态事件
 * @param {function} callbacks.onContent - 内容逐字推送 (accumulated: string)
 * @param {function} callbacks.onImages - 图片事件
 * @param {function} callbacks.onResult - 最终结果
 * @param {function} callbacks.onDone - 完成
 * @param {function} callbacks.onError - 错误
 * @returns {AbortController} 可用于取消请求
 */
export function diagnoseStream(query, sessionId, callbacks) {
  const controller = new AbortController()

  const body = { query }
  if (sessionId) body.session_id = sessionId

  fetch('/api/diagnose/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const errText = await response.text()
        callbacks.onError?.(`服务器错误 ${response.status}: ${errText}`)
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            const dataStr = line.slice(5).trim()
            if (!dataStr) continue
            try {
              const data = JSON.parse(dataStr)
              switch (currentEvent) {
                case 'status':
                  callbacks.onStatus?.(data)
                  break
                case 'content':
                  callbacks.onContent?.(data)
                  break
                case 'images':
                  callbacks.onImages?.(data)
                  break
                case 'result':
                  callbacks.onResult?.(data)
                  break
                case 'done':
                  callbacks.onDone?.(data)
                  break
                case 'error':
                  callbacks.onError?.(data.message || '未知错误')
                  break
              }
            } catch {
              // 非 JSON data，忽略
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError?.(err.message || '网络错误')
      }
    })

  return controller
}

/**
 * 获取会话历史
 * @param {string} sessionId - 会话ID
 * @returns {Promise<Object>} 会话历史
 */
export async function getSessionHistory(sessionId) {
  const response = await api.get(`/session/${sessionId}/history`)
  return response.data
}
