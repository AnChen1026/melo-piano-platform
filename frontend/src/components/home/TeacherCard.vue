<script setup lang="ts">
import type { TeacherCardData } from '@/mocks/home'

defineProps<{
  teacher: TeacherCardData
}>()

const emit = defineEmits<{
  viewCourses: [teacherName: string]
}>()
</script>

<template>
  <article class="teacher-card">
    <div class="teacher-card__photo">
      <!-- 還沒上傳照片的老師用示範照片，替代文字寫明不是本人 -->
      <img
        :src="teacher.photo"
        :alt="teacher.isSamplePhoto ? '示意照片' : `${teacher.name}的照片`"
        loading="lazy"
      />
    </div>
    <div class="teacher-card__body">
      <h3>{{ teacher.name }}</h3>
      <p v-if="teacher.specialty" class="teacher-card__specialty">{{ teacher.specialty }}</p>
      <p class="teacher-card__bio">{{ teacher.bio }}</p>
      <button type="button" @click="emit('viewCourses', teacher.name)">
        看這位老師的課
        <span aria-hidden="true">→</span>
      </button>
    </div>
  </article>
</template>

<style scoped>
.teacher-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 10px 10px 22px;
  border-radius: var(--radius-arch);
  background: var(--home-paper);
  text-align: center;
  transition: transform 0.4s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.4s ease;
}

.teacher-card:hover {
  transform: translateY(-6px);
  box-shadow: var(--shadow-soft);
}

/* 拱門形的照片框，呼應窗框與琴房的感覺 */
.teacher-card__photo {
  overflow: hidden;
  border-radius: var(--radius-arch);
  aspect-ratio: 3 / 4;
}

.teacher-card img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 22%;
  transition: transform 0.8s cubic-bezier(0.22, 1, 0.36, 1);
}

.teacher-card:hover img {
  transform: scale(1.04);
}

.teacher-card__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  padding: 18px 12px 0;
}

.teacher-card h3 {
  margin: 0;
  color: var(--home-ink);
  font-family: var(--font-serif);
  font-size: 22px;
  font-weight: 600;
}

.teacher-card__specialty {
  margin: 4px 0 0;
  color: var(--home-accent);
  font-size: 14px;
}

.teacher-card__bio {
  display: -webkit-box;
  flex: 1;
  margin: 12px 0 0;
  overflow: hidden;
  color: var(--home-muted);
  font-size: 14px;
  line-height: 1.7;
  /* 資料庫的簡介可能很長，最多顯示四行 */
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  line-clamp: 4;
}

.teacher-card button {
  display: inline-flex;
  gap: 6px;
  margin-top: 16px;
  padding: 0 0 2px;
  border: 0;
  border-bottom: 1px solid var(--home-wood);
  background: transparent;
  color: var(--home-ink);
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.2s ease;
}

.teacher-card button:hover {
  border-color: var(--home-accent);
}

.teacher-card button span {
  transition: translate 0.3s ease;
}

.teacher-card button:hover span {
  translate: 3px 0;
}

@media (prefers-reduced-motion: reduce) {
  .teacher-card,
  .teacher-card img {
    transition: none;
  }

  .teacher-card:hover,
  .teacher-card__initial {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  background: var(--home-cream);
  color: var(--home-accent);
  font-family: var(--font-serif);
  font-size: 64px;
  font-weight: 600;
}

.teacher-card:hover img {
    transform: none;
  }
}
</style>
