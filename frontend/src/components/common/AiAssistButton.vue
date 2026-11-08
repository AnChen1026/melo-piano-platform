<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { sendCourseChat, type ChatCourse } from '@/api/courseChat'
import { deliveryText, priceText } from '@/utils/format'

interface ChatMessage { role: 'assistant' | 'user'; text: string; courses?: ChatCourse[] }

const GREETING = '嗨！想學什麼樣的鋼琴？跟我聊聊你的程度、想彈的曲子、預算或地區，我會從老師已發布的課程裡幫你挑。平台怎麼用也可以問我。'

const open = ref(false)
const input = ref('')
const loading = ref(false)
const error = ref('')
// 開場白只顯示，不送給後端
const messages = ref<ChatMessage[]>([{ role: 'assistant', text: GREETING }])
const inputElement = ref<HTMLInputElement | null>(null)
const bodyElement = ref<HTMLElement | null>(null)

const canSubmit = computed(() => input.value.trim().length > 0 && !loading.value)
const started = computed(() => messages.value.length > 1)

async function toggle() {
  open.value = !open.value
  if (open.value) await nextTick(() => inputElement.value?.focus())
}

// 送出時捲到最底；回覆比較長，回來時捲到回覆開頭，課程卡片接在下面
async function scrollToLatest(fromStart = false) {
  await nextTick()
  const body = bodyElement.value
  if (!body) return
  const replies = body.querySelectorAll<HTMLElement>('.message--assistant')
  const latest = replies[replies.length - 1]
  const top = fromStart && latest ? latest.offsetTop - body.offsetTop - 12 : body.scrollHeight
  body.scrollTo({ top, behavior: 'smooth' })
}

async function submit() {
  const text = input.value.trim()
  if (!text || !canSubmit.value) return
  messages.value.push({ role: 'user', text })
  input.value = ''
  error.value = ''
  loading.value = true
  scrollToLatest()
  try {
    const history = messages.value.slice(1).map((message) => ({ role: message.role, content: message.text }))
    const next = await sendCourseChat(history)
    messages.value.push({ role: 'assistant', text: next.reply, courses: next.courses })
  } catch (caught) {
    messages.value.pop()
    input.value = text
    error.value = caught instanceof Error ? caught.message : '系統忙碌中，請稍後再試。'
  } finally {
    loading.value = false
    scrollToLatest(!error.value)
    await nextTick(() => inputElement.value?.focus())
  }
}

function restart() {
  error.value = ''
  input.value = ''
  messages.value = [{ role: 'assistant', text: GREETING }]
  nextTick(() => inputElement.value?.focus())
}
</script>

<template>
  <div class="ai-assist">
    <section v-if="open" class="ai-assist__panel" role="dialog" aria-label="AI 找課助理">
      <header class="ai-assist__header">
        <div>
          <p class="ai-assist__eyebrow">只推薦平台上已發布的課程</p>
          <h2>AI 找課助理</h2>
        </div>
        <button class="icon-button" type="button" aria-label="關閉找課助理" @click="open = false">×</button>
      </header>

      <div ref="bodyElement" class="ai-assist__body" aria-live="polite">
        <div class="messages">
          <template v-for="(message, index) in messages" :key="index">
            <p class="message" :class="`message--${message.role}`">{{ message.text }}</p>
            <div v-if="message.courses?.length" class="results">
              <article v-for="course in message.courses" :key="course.id" class="course-card">
                <p class="course-card__teacher">{{ course.teacher_name }}</p>
                <h3>{{ course.title }}</h3>
                <p>{{ [course.level, course.style, deliveryText(course.delivery_mode)].filter(Boolean).join('・') }}</p>
                <p>{{ course.region || '地區未填' }}・{{ priceText(course.price_per_lesson) }}</p>
                <p v-for="warning in course.warnings" :key="warning" class="course-card__warning">⚠ {{ warning }}</p>
                <RouterLink :to="`/courses/${course.id}/contact`">聯繫老師</RouterLink>
              </article>
            </div>
          </template>
          <p v-if="loading" class="message message--assistant">正在想…</p>
        </div>

        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </div>

      <form class="composer" @submit.prevent="submit">
        <label class="sr-only" for="course-request">跟找課助理說話</label>
        <input
          id="course-request"
          ref="inputElement"
          v-model="input"
          maxlength="1000"
          :disabled="loading"
          :placeholder="started ? '繼續聊，或補充條件…' : '例如：零基礎，想自彈自唱流行歌'"
        />
        <button type="submit" :disabled="!canSubmit">送出</button>
      </form>
      <button v-if="started" class="restart" type="button" :disabled="loading" @click="restart">重新開始</button>
    </section>

    <button type="button" class="ai-assist__button" :aria-expanded="open" @click="toggle">
      <span aria-hidden="true">✦</span> AI 找課
    </button>
  </div>
</template>

<style scoped>
.ai-assist { position: fixed; right: 24px; bottom: 24px; z-index: 30; display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
.ai-assist__button { display: inline-flex; align-items: center; gap: 8px; padding: 12px 20px; border: 1px solid var(--home-line); border-radius: var(--radius-pill); background: var(--home-paper); color: var(--home-ink); font-size: 15px; cursor: pointer; box-shadow: 0 10px 28px rgba(80, 58, 40, .16); }
.ai-assist__button span, .ai-assist__eyebrow { color: var(--home-accent); }
.ai-assist__button:hover { background: var(--home-cream); }
.ai-assist__panel { width: min(420px, calc(100vw - 32px)); max-height: min(680px, calc(100vh - 110px)); display: flex; flex-direction: column; overflow: hidden; background: var(--home-paper); border: 1px solid var(--home-line); border-radius: 22px; box-shadow: var(--shadow-soft); color: var(--home-ink); }
.ai-assist__header { display: flex; justify-content: space-between; gap: 16px; padding: 18px 20px 14px; border-bottom: 1px solid var(--home-line); }
.ai-assist__header h2 { margin: 3px 0 0; font-size: 20px; font-weight: 600; }
.ai-assist__eyebrow { margin: 0; font-size: 11px; letter-spacing: .08em; }
.icon-button { align-self: flex-start; border: 0; background: transparent; color: var(--home-muted); font-size: 25px; line-height: 1; cursor: pointer; }
.ai-assist__body { min-height: 190px; padding: 16px; overflow-y: auto; }
.messages { display: grid; gap: 9px; }
.message { width: fit-content; max-width: 88%; margin: 0; padding: 9px 12px; border-radius: 14px; font-size: 14px; line-height: 1.55; white-space: pre-line; }
.message--assistant { background: var(--home-cream); border-bottom-left-radius: 4px; }
.message--user { justify-self: end; background: var(--home-ink); color: var(--home-paper); border-bottom-right-radius: 4px; }
.results { display: grid; gap: 10px; margin: 2px 0 6px; }
.course-card { padding: 14px; border: 1px solid var(--home-line); border-radius: 14px; background: #fff; }
.course-card h3, .course-card p { margin: 0 0 5px; }
.course-card h3 { font-size: 16px; }
.course-card p { color: var(--home-muted); font-size: 12px; }
.course-card__teacher { color: var(--home-accent) !important; font-weight: 600; }
.course-card__warning { color: #a23a2f !important; }
.course-card a { display: inline-block; margin-top: 7px; color: var(--home-accent); font-size: 13px; font-weight: 600; }
.composer { display: flex; gap: 8px; padding: 13px 16px; border-top: 1px solid var(--home-line); }
.composer input { min-width: 0; flex: 1; padding: 10px 12px; border: 1px solid var(--home-line); border-radius: 10px; background: #fff; color: var(--home-ink); font: inherit; }
.composer button, .restart { border: 0; border-radius: 10px; background: var(--home-ink); color: var(--home-paper); cursor: pointer; }
.composer button { padding: 0 15px; }
.composer button:disabled, .restart:disabled { cursor: default; opacity: .45; }
.restart { margin: 0 16px 14px; padding: 11px; }
.error { margin: 12px 0 0; color: #a23a2f; font-size: 13px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 760px) { .ai-assist { right: 16px; bottom: 16px; } .ai-assist__button { padding: 10px 16px; font-size: 14px; } .ai-assist__panel { max-height: calc(100vh - 90px); } }
</style>
