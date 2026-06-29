<template>
  <div class="diagnosis-card">
    <!-- 头部：置信度 -->
    <div class="card-header">
      <div class="confidence-ring" :class="confidenceClass">
        <svg width="52" height="52" viewBox="0 0 52 52">
          <circle cx="26" cy="26" r="22" fill="none" stroke="currentColor" stroke-width="3" opacity="0.15"/>
          <circle cx="26" cy="26" r="22" fill="none" stroke="currentColor" stroke-width="3"
            :stroke-dasharray="circumference" :stroke-dashoffset="dashOffset"
            stroke-linecap="round" transform="rotate(-90 26 26)"/>
        </svg>
        <span class="confidence-text">{{ (data.confidence * 100).toFixed(0) }}%</span>
      </div>
      <div class="header-info">
        <div class="header-label">诊断置信度</div>
        <div class="header-status">{{ confidenceLabel }}</div>
      </div>
      <div v-if="data.has_hallucination" class="hallucination-badge">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        需人工复核
      </div>
    </div>

    <div class="card-body">
      <!-- 摘要 -->
      <div class="section">
        <div class="section-icon summary">S</div>
        <div class="section-content">
          <h3>问题摘要</h3>
          <p>{{ data.summary }}</p>
        </div>
      </div>

      <!-- 原因分析 -->
      <div class="section">
        <div class="section-icon cause">因</div>
        <div class="section-content">
          <h3>原因分析</h3>
          <div class="markdown-body" v-html="renderedCause" />
        </div>
      </div>

      <!-- 解决步骤 — 时间轴 -->
      <div v-if="data.solution_steps && data.solution_steps.length > 0" class="section">
        <div class="section-icon steps">解</div>
        <div class="section-content">
          <h3>解决方案</h3>
          <div class="timeline">
            <div v-for="(step, i) in data.solution_steps" :key="i" class="timeline-item">
              <div class="timeline-marker">{{ i + 1 }}</div>
              <div class="timeline-content">{{ step }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 知识库溯源 -->
      <div v-if="data.references && data.references.length > 0" class="section">
        <div class="section-icon refs">源</div>
        <div class="section-content">
          <h3>知识库溯源 · {{ data.references.length }} 条</h3>
          <div class="ref-list">
            <div v-for="(ref, i) in data.references" :key="i" class="ref-item" :class="{ verified: ref.verified }">
              <div class="ref-top">
                <span class="ref-source">{{ sourceLabel(ref.source) }}</span>
                <span class="ref-score">{{ (ref.score * 100).toFixed(1) }}%</span>
                <span v-if="ref.verified" class="ref-badge ok">已验</span>
              </div>
              <div v-if="ref.section_title" class="ref-section">{{ ref.section_title }}</div>
              <div v-if="ref.alarm_code" class="ref-alarm">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                {{ ref.alarm_code }}
              </div>
              <div v-if="ref.text_snippet" class="ref-text">{{ ref.text_snippet }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'

marked.setOptions({ breaks: true })

const SOURCE_LABELS = {
  fanuc: 'FANUC 数控', siemens: 'Siemens 840D', vmc850: 'VMC850 机床'
}
function sourceLabel(s) { return SOURCE_LABELS[s] || s }

const props = defineProps({ data: { type: Object, required: true } })

const circumference = 2 * Math.PI * 22

const confidenceClass = computed(() => {
  const c = props.data.confidence || 0
  if (c >= 0.8) return 'high'
  if (c >= 0.5) return 'mid'
  return 'low'
})
const confidenceLabel = computed(() => {
  const c = props.data.confidence || 0
  if (c >= 0.8) return '高置信度'
  if (c >= 0.5) return '中等置信度'
  return '需人工确认'
})
const dashOffset = computed(() => circumference * (1 - (props.data.confidence || 0)))

const renderedCause = computed(() => {
  const text = props.data.cause_analysis || ''
  return marked.parse(text)
})
</script>

<style scoped>
.diagnosis-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  animation: fadeUp 0.35s ease;
}
@keyframes fadeUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }

/* header */
.card-header {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
}
.confidence-ring {
  position: relative; flex-shrink: 0;
  width: 52px; height: 52px; display: flex; align-items: center; justify-content: center;
}
.confidence-ring.high { color: var(--success); }
.confidence-ring.mid { color: var(--warning); }
.confidence-ring.low { color: var(--danger); }
.confidence-text {
  position: absolute; font-size: 14px; font-weight: 700; color: var(--text-primary);
}
.header-info { flex: 1; }
.header-label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
.header-status { font-size: 15px; font-weight: 600; margin-top: 2px; }
.hallucination-badge {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px; background: rgba(231,76,60,0.12); border: 1px solid rgba(231,76,60,0.3);
  border-radius: 20px; color: var(--danger); font-size: 13px;
}

/* body */
.card-body { padding: 20px; display: flex; flex-direction: column; gap: 22px; }
.section { display: flex; gap: 14px; }
.section-icon {
  flex-shrink: 0; width: 32px; height: 32px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; color: #fff;
}
.section-icon.summary { background: var(--accent); }
.section-icon.cause { background: #8b5cf6; }
.section-icon.steps { background: var(--success); }
.section-icon.refs { background: var(--warning); }

.section-content { flex: 1; min-width: 0; }
.section-content h3 {
  font-size: 15px; font-weight: 600; margin-bottom: 8px; color: var(--text-primary);
}
.section-content p { color: var(--text-secondary); line-height: 1.6; }

/* timeline */
.timeline { position: relative; padding-left: 28px; }
.timeline::before {
  content: ''; position: absolute; left: 14px; top: 8px; bottom: 8px;
  width: 2px; background: var(--border-light);
}
.timeline-item { position: relative; margin-bottom: 14px; }
.timeline-item:last-child { margin-bottom: 0; }
.timeline-marker {
  position: absolute; left: -28px; top: 2px; width: 30px; height: 30px;
  border-radius: 50%; background: var(--bg-input); border: 2px solid var(--accent);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; color: var(--accent-light);
}
.timeline-content {
  padding: 10px 14px; background: var(--bg-input); border-radius: var(--radius);
  color: var(--text-secondary); line-height: 1.5; font-size: 14px;
}

/* references */
.ref-list { display: flex; flex-direction: column; gap: 8px; }
.ref-item {
  padding: 12px 14px; background: var(--bg-input); border-radius: var(--radius);
  border-left: 3px solid var(--border-light); transition: var(--transition);
}
.ref-item.verified { border-left-color: var(--success); }
.ref-top { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.ref-source { font-size: 13px; color: var(--accent-light); font-weight: 600; }
.ref-score { font-size: 12px; color: var(--text-muted); margin-left: auto; }
.ref-badge.ok {
  padding: 1px 8px; border-radius: 10px; background: rgba(46,204,113,0.15);
  color: var(--success); font-size: 11px;
}
.ref-section { font-size: 13px; color: var(--text-secondary); margin-bottom: 4px; }
.ref-alarm {
  display: flex; align-items: center; gap: 4px;
  font-size: 13px; color: var(--warning); margin-bottom: 4px;
}
.ref-text {
  font-size: 13px; color: var(--text-muted); line-height: 1.5;
  margin-top: 4px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
</style>
