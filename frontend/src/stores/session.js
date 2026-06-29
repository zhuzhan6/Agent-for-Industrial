import { reactive } from 'vue'

/**
 * 会话状态管理
 */
export const sessionStore = reactive({
  sessionId: null,
  messages: [],
  isFollowup: false,
  followupQuestion: '',
})

/**
 * 设置会话ID
 */
export function setSessionId(id) {
  sessionStore.sessionId = id
}

/**
 * 添加消息
 */
export function addMessage(role, content, data = {}) {
  sessionStore.messages.push({
    role,
    content,
    timestamp: new Date().toISOString(),
    ...data,
  })
}

/**
 * 设置追问状态
 */
export function setFollowupState(isFollowup, question = '') {
  sessionStore.isFollowup = isFollowup
  sessionStore.followupQuestion = question
}

/**
 * 重置会话
 */
export function resetSession() {
  sessionStore.sessionId = null
  sessionStore.messages = []
  sessionStore.isFollowup = false
  sessionStore.followupQuestion = ''
}
