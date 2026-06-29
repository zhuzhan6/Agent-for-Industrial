<template>
  <div class="app-shell">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="brand-icon">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
          </svg>
        </div>
        <div class="brand-text">
          <h1>工业排障</h1>
          <span>Intelligent Diagnostics</span>
        </div>
      </div>

      <div class="sidebar-stats">
        <div class="stat">
          <div class="stat-value" :class="{ active: sessionStore.sessionId }">
            {{ sessionStore.sessionId ? '●' : '○' }}
          </div>
          <div class="stat-label">会话状态</div>
        </div>
        <div class="stat">
          <div class="stat-value">{{ msgCount }}</div>
          <div class="stat-label">消息数</div>
        </div>
      </div>

      <div class="sidebar-actions">
        <el-button text class="new-chat-btn" @click="handleReset">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          新对话
        </el-button>
      </div>

      <div class="sidebar-footer">
        <div class="version">v1.0 · DeepSeek V4</div>
      </div>
    </aside>

    <!-- 主区域 -->
    <main class="main-area">
      <!-- 消息流 -->
      <div class="message-stream" ref="streamRef">
        <div v-if="messages.length === 0" class="welcome-screen">
          <div class="welcome-graphic">
            <div class="pulse-ring" />
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="1.5">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
          </div>
          <h2>工业设备智能排障系统</h2>
          <p>输入故障现象、报警代码或设备问题，AI 将自动检索知识库并给出诊断报告</p>
          <div class="welcome-tags">
            <button
              v-for="q in welcomeQueries"
              :key="q"
              class="welcome-tag"
              @click="handleSend(q)"
            >{{ q }}</button>
          </div>
        </div>

        <ChatMessage v-for="(msg, i) in messages" :key="i" :message="msg" />

        <!-- 流式输出中：显示正在输入的 assistant 消息 -->
        <div v-if="streaming" class="chat-msg assistant">
          <div class="msg-avatar assistant">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
          </div>
          <div class="msg-body">
            <div class="msg-bubble assistant streaming-bubble">
              {{ streamText }}<span class="cursor">▌</span>
            </div>
          </div>
        </div>

        <div v-if="loading && !streaming" class="typing-indicator">
          <div class="typing-avatar">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
          </div>
          <div class="typing-dots">
            <span class="dot" /><span class="dot" /><span class="dot" />
          </div>
          <span class="typing-text">分析中</span>
        </div>
      </div>

      <!-- 输入区 -->
      <ChatInput
        :loading="loading"
        :is-followup="isFollowup"
        :followup-question="followupQuestion"
        @send="handleSend"
      />
    </main>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import ChatMessage from '../components/ChatMessage.vue'
import ChatInput from '../components/ChatInput.vue'
import { diagnoseStream } from '../api/diagnose.js'
import { sessionStore, setSessionId, addMessage, setFollowupState, resetSession } from '../stores/session.js'

const streamRef = ref(null)
const loading = ref(false)
const streaming = ref(false)
const streamText = ref('')
let abortController = null

const messages = computed(() => sessionStore.messages)
const isFollowup = computed(() => sessionStore.isFollowup)
const followupQuestion = computed(() => sessionStore.followupQuestion)
const msgCount = computed(() => sessionStore.messages.length)

const welcomeQueries = [
  'FANUC 报警 SV0410 怎么解决',
  '主轴高速旋转时异响',
  '刀库换刀卡死',
  'Siemens 840D 报警 27253',
]

watch(messages, () => {
  nextTick(() => {
    if (streamRef.value) streamRef.value.scrollTop = streamRef.value.scrollHeight
  })
}, { deep: true })

async function handleSend(text) {
  loading.value = true
  streaming.value = false
  streamText.value = ''
  addMessage('user', text)

  let finalResult = null

  let accumulatedText = ''

  abortController = diagnoseStream(text, sessionStore.sessionId, {
    onStatus() {
      // 状态事件：开始分析，显示 loading
    },
    onContent(data) {
      // 逐字推送 - 累积文字
      if (!streaming.value) streaming.value = true
      accumulatedText += data.text || ''
      streamText.value = accumulatedText
      nextTick(() => {
        if (streamRef.value) streamRef.value.scrollTop = streamRef.value.scrollHeight
      })
    },
    onImages(data) {
      // 图片事件：暂存，等 result 一起渲染
      if (finalResult) finalResult.images = data.images
    },
    onResult(data) {
      finalResult = data
      if (data.session_id) setSessionId(data.session_id)
    },
    onDone() {
      streaming.value = false
      loading.value = false
      if (finalResult) {
        if (finalResult.needs_followup) {
          setFollowupState(true, finalResult.followup_question)
          addMessage('assistant', finalResult.followup_question)
        } else {
          setFollowupState(false)
          addMessage('assistant', finalResult.summary || '诊断完成', {
            data: {
              summary: finalResult.summary,
              cause_analysis: finalResult.cause_analysis,
              solution_steps: finalResult.solution_steps,
              references: finalResult.references,
              images: finalResult.images,
              confidence: finalResult.confidence,
              has_hallucination: finalResult.has_hallucination,
            },
          })
        }
      } else if (accumulatedText) {
        // 闲聊或无 result 事件的情况，直接显示累积的文字
        setFollowupState(false)
        addMessage('assistant', accumulatedText)
      }
      streamText.value = ''
      accumulatedText = ''
      abortController = null
    },
    onError(errMsg) {
      streaming.value = false
      loading.value = false
      ElMessage.error(errMsg)
      addMessage('assistant', errMsg)
      streamText.value = ''
      accumulatedText = ''
      abortController = null
    },
  })
}

function handleReset() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  streaming.value = false
  loading.value = false
  streamText.value = ''
  accumulatedText = ''
  resetSession()
}
</script>

<style scoped>
.app-shell {
  display: flex; height: 100vh; overflow: hidden;
}

/* sidebar */
.sidebar {
  width: 220px; flex-shrink: 0; background: var(--bg-secondary);
  border-right: 1px solid var(--border); display: flex; flex-direction: column;
  padding: 20px 16px; gap: 24px;
}
.sidebar-brand { display: flex; align-items: center; gap: 12px; }
.brand-icon { color: var(--accent); }
.brand-text h1 { font-size: 16px; font-weight: 700; color: var(--text-primary); line-height: 1.2; }
.brand-text span { font-size: 11px; color: var(--text-muted); letter-spacing: 0.5px; }
.sidebar-stats { display: flex; gap: 16px; }
.stat { flex: 1; text-align: center; padding: 10px 8px; background: var(--bg-card); border-radius: var(--radius); }
.stat-value { font-size: 16px; font-weight: 700; color: var(--text-primary); }
.stat-value.active { color: var(--success); }
.stat-label { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.sidebar-actions { flex: 1; }
.new-chat-btn { width: 100%; justify-content: flex-start; color: var(--text-secondary) !important; font-size: 14px; gap: 8px; padding: 10px 12px; border-radius: var(--radius); transition: var(--transition); }
.new-chat-btn:hover { background: var(--bg-hover); color: var(--text-primary) !important; }
.sidebar-footer { border-top: 1px solid var(--border); padding-top: 14px; }
.version { font-size: 11px; color: var(--text-muted); }

/* main */
.main-area {
  flex: 1; display: flex; flex-direction: column; min-width: 0; background: var(--bg-primary);
}
.message-stream {
  flex: 1; overflow-y: auto; padding: 24px 32px;
}

/* welcome */
.welcome-screen {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 100%; text-align: center; padding: 40px;
}
.welcome-graphic { position: relative; margin-bottom: 24px; }
.pulse-ring {
  position: absolute; inset: -16px; border-radius: 50%;
  border: 2px solid var(--accent); opacity: 0.2; animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { transform: scale(0.8); opacity: 0.1; } 50% { transform: scale(1.1); opacity: 0.3; } }
.welcome-screen h2 { font-size: 22px; font-weight: 700; margin-bottom: 8px; color: var(--text-primary); }
.welcome-screen p { font-size: 14px; color: var(--text-muted); max-width: 480px; margin-bottom: 28px; line-height: 1.6; }
.welcome-tags { display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }
.welcome-tag {
  padding: 9px 20px; background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 24px; color: var(--text-secondary); font-size: 14px; cursor: pointer;
  transition: var(--transition); font-family: inherit;
}
.welcome-tag:hover { border-color: var(--accent); color: var(--accent-light); background: var(--bg-hover); transform: translateY(-1px); }

/* typing */
.typing-indicator {
  display: flex; align-items: center; gap: 10px; padding: 12px 0;
}
.typing-avatar {
  width: 30px; height: 30px; border-radius: 50%;
  background: var(--bg-hover); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center; color: var(--accent-light);
}
.typing-dots { display: flex; gap: 4px; }
.dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--accent);
  animation: bounce 1.2s ease-in-out infinite;
}
.dot:nth-child(2) { animation-delay: 0.15s; }
.dot:nth-child(3) { animation-delay: 0.3s; }
@keyframes bounce { 0%, 60%, 100% { opacity: 0.2; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-4px); } }
.typing-text { font-size: 13px; color: var(--text-muted); }

/* 流式消息 */
.chat-msg { display: flex; gap: 12px; margin-bottom: 20px; }
.chat-msg.assistant { max-width: 85%; }
.msg-avatar {
  flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
}
.msg-avatar.assistant { background: var(--bg-hover); color: var(--accent-light); border: 1px solid var(--border); }
.msg-body { flex: 1; min-width: 0; }
.msg-bubble {
  display: inline-block; padding: 10px 16px; border-radius: var(--radius);
  line-height: 1.55; word-break: break-word; white-space: pre-wrap;
}
.msg-bubble.assistant {
  background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border);
  border-bottom-left-radius: 3px; max-width: 100%;
}
.streaming-bubble { min-height: 2em; }
.cursor {
  color: var(--accent);
  animation: blink 0.6s step-end infinite;
  font-weight: 300;
}
@keyframes blink { 50% { opacity: 0; } }
</style>
