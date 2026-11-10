<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import CourseImage from './CourseImage.vue'
import type { CourseSummary } from '@/types/course'
import { DELIVERY_LABELS } from '@/utils/format'

const props = defineProps<{
  course: CourseSummary
}>()

const HOVER_DELAY_MS = 800

const open = ref(false)
const grown = ref(false)
const previewStyle = ref<Record<string, string>>({})
let showTimer = 0
let hideTimer = 0
let growFrame = 0

const imagePosition = computed(() => {
  const text = `${props.course.style ?? ''}${props.course.title}`
  if (text.includes('流行')) return 'center 100%'
  if (text.includes('古典') || text.includes('爵士')) return 'center 68%'
  return 'center'
})

const priceText = computed(() => {
  const price = props.course.pricePerLesson
  return price === null ? '價格洽詢' : `NT$ ${price.toLocaleString('zh-TW')}`
})

const metaText = computed(() => {
  const mode = props.course.deliveryMode
  return [props.course.level, mode ? (DELIVERY_LABELS[mode] ?? mode) : null, props.course.region]
    .filter((item) => item)
    .join(' · ')
})

function placePreview(target: HTMLElement) {
  const rect = target.getBoundingClientRect()
  const width = Math.min(340, Math.max(260, rect.width * 1.35))
  const height = 390
  let left = rect.left + rect.width / 2 - width / 2
  left = Math.max(12, Math.min(left, window.innerWidth - width - 12))
  let top = rect.top - 12
  const minTop = 80
  if (top + height > window.innerHeight - 12) {
    top = window.innerHeight - height - 12
  }
  top = Math.max(minTop, top)
  previewStyle.value = {
    '--from-top': `${rect.top}px`,
    '--from-left': `${rect.left}px`,
    '--from-width': `${rect.width}px`,
    '--to-top': `${top}px`,
    '--to-left': `${left}px`,
    '--to-width': `${width}px`,
  }
}

function startGrow() {
  if (growFrame) cancelAnimationFrame(growFrame)
  grown.value = false
  growFrame = requestAnimationFrame(() => {
    growFrame = requestAnimationFrame(() => {
      grown.value = true
    })
  })
}

function showPreview(event: MouseEvent) {
  window.clearTimeout(hideTimer)
  window.clearTimeout(showTimer)
  const target = event.currentTarget as HTMLElement
  showTimer = window.setTimeout(() => {
    placePreview(target)
    open.value = true
    startGrow()
  }, HOVER_DELAY_MS)
}

function hidePreviewSoon() {
  window.clearTimeout(showTimer)
  window.clearTimeout(hideTimer)
  if (!open.value) return
  hideTimer = window.setTimeout(() => {
    grown.value = false
    hideTimer = window.setTimeout(() => {
      open.value = false
    }, 320)
  }, 180)
}

function keepPreview() {
  window.clearTimeout(hideTimer)
  if (open.value) grown.value = true
}

function closePreview() {
  window.clearTimeout(showTimer)
  if (growFrame) cancelAnimationFrame(growFrame)
  grown.value = false
  open.value = false
}

window.addEventListener('scroll', closePreview, true)
onBeforeUnmount(() => {
  window.removeEventListener('scroll', closePreview, true)
  window.clearTimeout(showTimer)
  window.clearTimeout(hideTimer)
  if (growFrame) cancelAnimationFrame(growFrame)
})
</script>

<template>
  <article class="poster" @mouseenter="showPreview" @mouseleave="hidePreviewSoon">
    <div class="poster__face">
      <CourseImage :src="course.imageUrl" :alt="course.title" :position="imagePosition" />
      <div class="poster__caption">
        <p class="poster__title">{{ course.title }}</p>
        <p v-if="course.teacherName" class="poster__teacher">{{ course.teacherName }}</p>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="open"
        class="preview"
        :class="{ 'preview--grown': grown }"
        :style="previewStyle"
        @mouseenter="keepPreview"
        @mouseleave="hidePreviewSoon"
      >
        <div class="preview__image">
          <CourseImage :src="course.imageUrl" :alt="course.title" :position="imagePosition" />
        </div>
        <div class="preview__body">
          <div class="preview__body-inner">
            <h3 class="preview__title">{{ course.title }}</h3>
            <p v-if="course.teacherName" class="preview__line">老師：{{ course.teacherName }}</p>
            <p v-if="metaText" class="preview__line">{{ metaText }}</p>
            <p v-if="course.timeSlots" class="preview__line">時段：{{ course.timeSlots }}</p>
            <p class="preview__price">{{ priceText }}</p>
            <a class="preview__contact" :href="`/courses/${course.id}/contact`">與老師聯繫</a>
          </div>
        </div>
      </div>
    </Teleport>
  </article>
</template>

<style scoped>
.poster {
  flex: 0 0 calc((100% - 40px) / 6);
  min-width: 0;
}

.poster__face {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: 6px;
  overflow: hidden;
  background: #2a2a2a;
  cursor: pointer;
}

.poster__caption {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  padding: 28px 10px 8px;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.82));
  color: #fff;
}

.poster__title,
.poster__teacher {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.poster__title {
  font-size: 15px;
  font-weight: 700;
}

.poster__teacher {
  margin-top: 2px;
  font-size: 12px;
  color: #e6e6e6;
}

.preview {
  position: fixed;
  z-index: 30;
  top: var(--from-top);
  left: var(--from-left);
  width: var(--from-width);
  overflow: hidden;
  border-radius: 8px;
  background: #181818;
  color: #fff;
  box-shadow: none;
  transition:
    top 0.32s ease,
    left 0.32s ease,
    width 0.32s ease,
    box-shadow 0.32s ease;
}

.preview--grown {
  top: var(--to-top);
  left: var(--to-left);
  width: var(--to-width);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55);
}

.preview__image {
  aspect-ratio: 16 / 9;
}

.preview__body {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.32s ease;
}

.preview--grown .preview__body {
  grid-template-rows: 1fr;
}

.preview__body-inner {
  min-height: 0;
  overflow: hidden;
  padding: 0 14px;
  transition: padding 0.32s ease;
}

.preview--grown .preview__body-inner {
  padding: 12px 14px 14px;
}

.preview__title {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 700;
}

.preview__line {
  margin: 0;
  color: #d0d0d0;
  font-size: 14px;
  line-height: 1.5;
}

.preview__price {
  margin: 8px 0 0;
  font-size: 16px;
  font-weight: 700;
}

.preview__contact {
  display: inline-flex;
  align-items: center;
  margin-top: 12px;
  padding: 8px 16px;
  border-radius: 999px;
  background: #fff;
  color: #141414;
  font-size: 14px;
  font-weight: 700;
}

.preview__contact:hover {
  background: #e8e8e8;
}

@media (max-width: 1100px) {
  .poster {
    flex-basis: calc((100% - 16px) / 3);
  }
}

@media (max-width: 700px) {
  .poster {
    flex-basis: calc((100% - 8px) / 2);
  }

  .poster__title {
    font-size: 13px;
  }
}
</style>
