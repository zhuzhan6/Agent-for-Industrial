<template>
  <div class="chat-msg" :class="[message.role, { 'has-result': message.role === 'assistant' && message.data }]">
    <!-- 头像 -->
    <div class="msg-avatar" :class="message.role">
      <svg v-if="message.role === 'user'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
      </svg>
      <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
      </svg>
    </div>

    <div class="msg-body">
      <!-- 纯文本消息 -->
      <div v-if="!message.data" class="msg-bubble" :class="message.role">
        {{ message.content }}
      </div>

      <!-- 诊断结果 -->
      <DiagnosisResult v-else :data="message.data" />

      <div class="msg-time">{{ formatTime(message.timestamp) }}</div>
    </div>
  </div>
</template>

<script setup>
import DiagnosisResult from './DiagnosisResult.vue'

const props = defineProps({ message: { type: Object, required: true } })

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.chat-msg {
  display: flex; gap: 12px; margin-bottom: 20px; animation: msgIn 0.25s ease;
}
.chat-msg.user { flex-direction: row-reverse; }
.chat-msg.has-result { max-width: 100%; }
.chat-msg:not(.has-result) { max-width: 85%; }

@keyframes msgIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }

.msg-avatar {
  flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
}
.msg-avatar.user { background: var(--accent); color: #fff; }
.msg-avatar.assistant { background: var(--bg-hover); color: var(--accent-light); border: 1px solid var(--border); }

.msg-body { flex: 1; min-width: 0; }
.msg-bubble {
  display: inline-block; padding: 10px 16px; border-radius: var(--radius);
  line-height: 1.55; word-break: break-word; white-space: pre-wrap;
}
.msg-bubble.user {
  background: var(--accent); color: #fff;
  border-bottom-right-radius: 3px; max-width: 100%;
}
.msg-bubble.assistant {
  background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border);
  border-bottom-left-radius: 3px; max-width: 100%;
}
.msg-time { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.user .msg-time { text-align: right; }
</style>
