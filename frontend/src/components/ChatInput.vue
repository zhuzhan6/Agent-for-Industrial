<template>
  <div class="chat-input-area">
    <!-- 追问提示 -->
    <div v-if="isFollowup" class="followup-bar">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span>{{ followupQuestion }}</span>
    </div>

    <!-- 输入行 -->
    <div class="input-row">
      <textarea
        v-model="text"
        ref="textareaRef"
        class="chat-textarea"
        :placeholder="isFollowup ? '输入补充信息...' : '描述故障现象、报警代码或设备问题...'"
        rows="1"
        @keydown.enter.exact.prevent="handleSend"
        @input="autoResize"
        :disabled="loading"
      />
      <button class="send-btn" :class="{ loading }" :disabled="!text.trim() || loading" @click="handleSend">
        <svg v-if="!loading" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
        </svg>
        <span v-else class="spinner" />
      </button>
    </div>

    <!-- 快捷标签 -->
    <div v-if="!isFollowup" class="quick-tags">
      <button v-for="tag in quickTags" :key="tag" class="quick-tag" @click="handleQuick(tag)">{{ tag }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'

const props = defineProps({
  loading: Boolean,
  isFollowup: Boolean,
  followupQuestion: String,
})
const emit = defineEmits(['send'])
const text = ref('')
const textareaRef = ref(null)

const quickTags = ['主轴异响', '刀库换刀卡死', 'SV0410 报警', 'FANUC 系统故障']

function autoResize() {
  nextTick(() => {
    const el = textareaRef.value
    if (el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 120) + 'px' }
  })
}
function handleSend() {
  if (!text.value.trim() || props.loading) return
  emit('send', text.value.trim())
  text.value = ''
  nextTick(autoResize)
}
function handleQuick(tag) {
  emit('send', tag)
}
</script>

<style scoped>
.chat-input-area {
  padding: 16px 24px 20px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border);
}
.followup-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; margin-bottom: 12px;
  background: rgba(243,156,18,0.1); border: 1px solid rgba(243,156,18,0.25);
  border-radius: var(--radius); color: var(--warning); font-size: 14px;
}
.input-row { display: flex; gap: 10px; align-items: flex-end; }
.chat-textarea {
  flex: 1; background: var(--bg-input); border: 1px solid var(--border);
  border-radius: var(--radius); color: var(--text-primary); font-size: 14px;
  font-family: inherit; padding: 12px 16px; resize: none; min-height: 44px;
  max-height: 120px; outline: none; transition: var(--transition); line-height: 1.5;
}
.chat-textarea::placeholder { color: var(--text-muted); }
.chat-textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }
.chat-textarea:disabled { opacity: 0.4; }
.send-btn {
  flex-shrink: 0; width: 44px; height: 44px; border-radius: 50%;
  background: var(--accent); border: none; color: #fff; cursor: pointer;
  display: flex; align-items: center; justify-content: center; transition: var(--transition);
}
.send-btn:hover:not(:disabled) { background: var(--accent-light); transform: scale(1.05); }
.send-btn:disabled { opacity: 0.25; cursor: not-allowed; }
.spinner {
  width: 18px; height: 18px; border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff; border-radius: 50%; animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.quick-tags { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.quick-tag {
  background: var(--bg-input); border: 1px solid var(--border); color: var(--text-secondary);
  padding: 5px 14px; border-radius: 20px; font-size: 13px; cursor: pointer;
  transition: var(--transition); font-family: inherit;
}
.quick-tag:hover { border-color: var(--accent); color: var(--accent-light); background: var(--bg-hover); }
</style>
