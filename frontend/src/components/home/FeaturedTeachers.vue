<script setup lang="ts">
import TeacherCard from './TeacherCard.vue'
import SectionHeading from './SectionHeading.vue'
import type { TeacherCardData } from '@/mocks/home'

defineProps<{
  teachers: TeacherCardData[]
  // 讀取中或讀取失敗時的說明；空字串代表讀好了
  status?: string
}>()

const emit = defineEmits<{
  viewCourses: [teacherName: string]
}>()
</script>

<template>
  <section id="teachers" class="teachers" aria-labelledby="teachers-title">
    <SectionHeading
      v-reveal
      label="認識老師"
      title="讓專業的老師"
      accent="陪你走下去"
      heading-id="teachers-title"
      align="center"
    >
      每位老師都經過平台審核。先看看誰的風格適合你，再從課程洽詢。
    </SectionHeading>

    <p v-if="status" class="teachers__empty">{{ status }}</p>
    <p v-else-if="teachers.length === 0" class="teachers__empty">找不到符合的老師。</p>
    <div v-else class="teachers__grid">
      <TeacherCard
        v-for="(teacher, index) in teachers"
        :key="teacher.id"
        v-reveal="index * 90"
        :teacher="teacher"
        @view-courses="emit('viewCourses', $event)"
      />
    </div>
  </section>
</template>

<style scoped>
.teachers {
  padding: var(--section-space) 0;
  background: var(--home-cream);
}

.teachers > * {
  width: min(1160px, calc(100% - 48px));
}

.teachers__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 22px;
  margin: 48px auto 0;
}

.teachers__empty {
  margin: 32px auto 0;
  color: var(--home-muted);
  text-align: center;
}

@media (max-width: 980px) {
  .teachers__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .teachers > * {
    width: calc(100% - 32px);
  }

  .teachers__grid {
    gap: 14px;
  }
}
</style>
