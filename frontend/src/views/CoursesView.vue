<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CourseCard from '@/components/home/CourseCard.vue'
import CourseDetailDialog from '@/components/home/CourseDetailDialog.vue'
import SectionHeading from '@/components/home/SectionHeading.vue'
import Footer from '@/components/home/Footer.vue'
import { fetchPublishedCourses } from '@/api/courses'
import { HYBRID_LABEL, toCourseCard } from '@/utils/courseCard'
import { courseLevels, type CourseCardData } from '@/mocks/home'

// 全部課程：一次列出所有已發布課程，可用關鍵字、風格、程度、上課方式、地區、價格篩選
const route = useRoute()
const router = useRouter()

const courses = ref<CourseCardData[]>([])
const status = ref('正在讀取已發布的課程…')
const selectedCourse = ref<CourseCardData | null>(null)

const priceOptions = [1000, 1500, 2000, 3000]
const sortOptions = [
  { value: '', label: '預設排序' },
  { value: 'price-asc', label: '價格低到高' },
  { value: 'price-desc', label: '價格高到低' },
]

function queryText(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

// 篩選條件放在網址上，重新整理或返回時條件還在
const filters = reactive({
  keyword: queryText('q'),
  style: queryText('style'),
  level: queryText('level'),
  format: queryText('format'),
  region: queryText('region'),
  maxPrice: queryText('maxPrice'),
  sort: queryText('sort'),
})

watch(filters, () => {
  const query: Record<string, string> = {}
  if (filters.keyword.trim()) query.q = filters.keyword.trim()
  if (filters.style) query.style = filters.style
  if (filters.level) query.level = filters.level
  if (filters.format) query.format = filters.format
  if (filters.region) query.region = filters.region
  if (filters.maxPrice) query.maxPrice = filters.maxPrice
  if (filters.sort) query.sort = filters.sort
  router.replace({ query })
})

onMounted(async () => {
  try {
    courses.value = (await fetchPublishedCourses()).map(toCourseCard)
    status.value = ''
  } catch (problem) {
    status.value = problem instanceof Error ? problem.message : '讀不到課程，請確認後端有啟動。'
  }
})

function distinct(values: (string | null)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort((a, b) =>
    a.localeCompare(b, 'zh-Hant'),
  )
}

const styleOptions = computed(() => distinct(courses.value.map((course) => course.category)))
const regionOptions = computed(() => distinct(courses.value.map((course) => course.region)))

const hasFilter = computed(() =>
  Boolean(filters.keyword.trim() || filters.style || filters.level || filters.format || filters.region || filters.maxPrice),
)

const filteredCourses = computed(() => {
  const text = filters.keyword.trim().toLowerCase()
  const maxPrice = filters.maxPrice ? Number(filters.maxPrice) : null
  const result = courses.value.filter((course) => {
    if (text) {
      const fields = [course.title, course.teacherName, course.category, course.summary, course.description ?? '']
      if (!fields.some((field) => field.toLowerCase().includes(text))) return false
    }
    if (filters.style && course.category !== filters.style) return false
    if (filters.level && course.level !== filters.level) return false
    if (filters.format && course.format !== filters.format && course.format !== HYBRID_LABEL) return false
    if (filters.region && course.region !== filters.region) return false
    if (maxPrice !== null && (course.price === null || course.price > maxPrice)) return false
    return true
  })
  // 沒填價格的課排在最後
  if (filters.sort === 'price-asc') {
    result.sort((a, b) => (a.price ?? Infinity) - (b.price ?? Infinity))
  } else if (filters.sort === 'price-desc') {
    result.sort((a, b) => (b.price ?? -Infinity) - (a.price ?? -Infinity))
  }
  return result
})

function clearFilters() {
  Object.assign(filters, { keyword: '', style: '', level: '', format: '', region: '', maxPrice: '', sort: '' })
}
</script>

<template>
  <div class="all-courses">
    <section class="all-courses__inner" aria-labelledby="all-courses-title">
      <RouterLink :to="{ name: 'home', hash: '#courses' }" class="all-courses__back">← 回首頁</RouterLink>

      <SectionHeading label="全部課程" title="慢慢挑，" accent="找到想上的那一門" heading-id="all-courses-title">
        這裡列出所有老師已發布的鋼琴課。用下面的條件縮小範圍，點課程卡就能看詳情、與老師接洽。
      </SectionHeading>

      <form class="filters" role="search" @submit.prevent>
        <label class="filters__search">
          <span class="sr-only">關鍵字</span>
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5" />
            <path d="m10.5 10.5 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
          <input v-model="filters.keyword" type="search" placeholder="搜尋課名、老師或課程介紹" />
        </label>

        <div class="filters__selects">
          <label>
            <span>風格</span>
            <select v-model="filters.style">
              <option value="">全部風格</option>
              <option v-for="item in styleOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label>
            <span>程度</span>
            <select v-model="filters.level">
              <option value="">全部程度</option>
              <option v-for="item in courseLevels" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label>
            <span>上課方式</span>
            <select v-model="filters.format">
              <option value="">線上與實體</option>
              <option value="線上">線上</option>
              <option value="實體">實體</option>
            </select>
          </label>
          <label>
            <span>地區</span>
            <select v-model="filters.region">
              <option value="">全部地區</option>
              <option v-for="item in regionOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label>
            <span>每堂價格</span>
            <select v-model="filters.maxPrice">
              <option value="">不限</option>
              <option v-for="item in priceOptions" :key="item" :value="String(item)">
                NT$ {{ item.toLocaleString('zh-TW') }} 以內
              </option>
            </select>
          </label>
          <label>
            <span>排序</span>
            <select v-model="filters.sort">
              <option v-for="item in sortOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
        </div>
      </form>

      <div class="all-courses__summary">
        <p v-if="!status">
          共 <strong>{{ filteredCourses.length }}</strong> 門課<template v-if="hasFilter">符合條件</template>
        </p>
        <button v-if="hasFilter" type="button" @click="clearFilters">清除條件</button>
      </div>

      <p v-if="status" class="all-courses__empty">{{ status }}</p>
      <p v-else-if="filteredCourses.length === 0" class="all-courses__empty">
        目前沒有符合的課程，換個條件看看。
      </p>
      <div v-else class="all-courses__grid">
        <CourseCard
          v-for="course in filteredCourses"
          :key="course.id"
          :course="course"
          @view-course="selectedCourse = $event"
        />
      </div>
    </section>
    <Footer />
    <CourseDetailDialog :course="selectedCourse" @close="selectedCourse = null" />
  </div>
</template>

<style scoped>
.all-courses {
  min-height: 100vh;
  background: var(--home-bg);
  color: var(--home-ink);
}

.all-courses__inner {
  width: min(1160px, calc(100% - 48px));
  margin: 0 auto;
  padding: 140px 0 var(--section-space);
}

.all-courses__back {
  display: inline-block;
  margin-bottom: 28px;
  color: var(--home-accent);
  font-size: 14px;
  text-decoration: none;
}

.all-courses__back:hover {
  color: var(--home-accent-dark);
}

.filters {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 40px;
  padding: 24px;
  border: 1px solid var(--home-line);
  border-radius: var(--radius-card);
  background: var(--home-paper);
}

.filters__search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 18px;
  border: 1px solid var(--home-wood);
  border-radius: var(--radius-pill);
  background: var(--home-bg);
  color: var(--home-muted);
  transition: border-color 0.2s ease;
}

.filters__search:focus-within {
  border-color: var(--home-accent);
}

.filters__search input {
  flex: 1;
  min-width: 0;
  padding: 12px 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--home-ink);
  font: inherit;
  font-size: 15px;
}

.filters__selects {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
}

.filters__selects label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--home-muted);
  font-size: 13px;
}

.filters__selects select {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--home-wood);
  border-radius: 12px;
  background: var(--home-bg);
  color: var(--home-ink);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}

.filters__selects select:focus {
  outline: none;
  border-color: var(--home-accent);
}

.all-courses__summary {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 24px;
  margin-top: 32px;
}

.all-courses__summary p {
  margin: 0;
  color: var(--home-muted);
  font-size: 14px;
}

.all-courses__summary strong {
  color: var(--home-ink);
  font-weight: 600;
}

.all-courses__summary button {
  border: 0;
  border-bottom: 1px solid var(--home-accent);
  background: transparent;
  color: var(--home-accent);
  font-size: 14px;
  cursor: pointer;
}

.all-courses__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 40px 24px;
  margin-top: 24px;
}

.all-courses__empty {
  margin-top: 32px;
  color: var(--home-muted);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

@media (max-width: 980px) {
  .filters__selects {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .all-courses__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .all-courses__inner {
    width: calc(100% - 32px);
    padding-top: 112px;
  }

  .filters {
    padding: 16px;
  }

  .filters__selects {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .all-courses__grid {
    grid-template-columns: 1fr;
  }
}
</style>
