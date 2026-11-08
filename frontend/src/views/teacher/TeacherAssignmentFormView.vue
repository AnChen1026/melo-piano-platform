<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/console/PageHeader.vue'
import PageToolbar from '@/components/console/PageToolbar.vue'
import NoticeDialog from '@/components/console/NoticeDialog.vue'
import QuizQuestionCard from '@/components/console/QuizQuestionCard.vue'
import { useLeaveGuard } from '@/composables/useLeaveGuard'
import {
  createAssignment,
  createQuizJob,
  discardQuizJob,
  fetchMyCourses,
  fetchMyStudents,
  fetchQuizJob,
  fetchQuizJobs,
  retryQuizJob,
} from '@/api/teacher'
import type { Assignment, BoundStudent, Course, QuizDifficulty, QuizDraftQuestion, QuizJob, QuizQuestionType } from '@/types/api'
import { QUIZ_DIFFICULTY_LABELS, QUIZ_TYPE_LABELS, fileSizeText, formatDateTime } from '@/utils/format'

// 設計稿的「作業管理」：演奏作業上傳／題庫作業上傳兩個分頁。
// 演奏作業：選課程與學生、期限、參考 MIDI。
// 題庫作業：上傳教材（PDF／TXT）＋出題設定，按「AI 生成題目並預覽」在背景出題（本機千問可能要好幾分鐘，可以先離開），
// 完成後在「AI 出題紀錄」按「審查」看題目、可以直接點選項改正確答案或刪題，「儲存題目」後再「儲存作業」發給學生。
const route = useRoute()
const router = useRouter()
const courses = ref<Course[]>([])
const students = ref<BoundStudent[]>([])
const kind = ref<Assignment['kind']>('performance')
const form = reactive({ courseId: '', studentId: '', title: '', dueDate: '', description: '' })
const midi = ref<File | null>(null)
const errors = reactive<Record<string, string>>({})
const serverError = ref('')
const saving = ref(false)
const done = ref(false)
const dirty = ref(false)
const midiInput = ref<HTMLInputElement | null>(null)

// ---------- 題庫作業
const COUNT_PRESETS = [10, 20, 25]
const TYPE_OPTIONS: { value: QuizQuestionType; label: string }[] = [
  { value: 'single', label: '單選題' },
  { value: 'multiple', label: '多選題' },
  { value: 'truefalse', label: '是非題' },
]
const DIFFICULTY_OPTIONS: { value: QuizDifficulty; label: string }[] = [
  { value: 'easy', label: '簡單' },
  { value: 'medium', label: '中等' },
  { value: 'hard', label: '困難' },
  { value: 'mixed', label: '混合' },
]
const quiz = reactive({
  file: null as File | null,
  count: 10 as number | 'custom',
  customCount: '' as number | '',
  types: ['single'] as QuizQuestionType[],
  difficulty: 'easy' as QuizDifficulty,
  useOcr: false,
})
const preview = ref<QuizDraftQuestion[]>([])
// 老師按過「儲存題目」的題目，儲存作業時送這份
const questions = ref<QuizDraftQuestion[]>([])
const previewing = ref(false)
const previewIndex = ref(0)
const editing = ref(false)
const submitting = ref(false)
const notice = ref('')
const quizFileInput = ref<HTMLInputElement | null>(null)
// AI 出題紀錄（背景工作）；正在審查的是哪一次
const jobs = ref<QuizJob[]>([])
const reviewing = ref<QuizJob | null>(null)
const discarding = ref<QuizJob | null>(null)
let pollTimer = 0

const JOB_STATUS: Record<string, string> = { queued: '排隊中', running: '出題中', succeeded: '待審查', failed: '失敗' }
const activeJobs = computed(() => jobs.value.some((job) => job.status === 'queued' || job.status === 'running'))

const previewQuestion = computed(() => preview.value[previewIndex.value])
const questionCount = computed(() => (quiz.count === 'custom' ? Number(quiz.customCount) : quiz.count))
const requestedCount = computed(() => reviewing.value?.settings.count ?? questionCount.value)

// 只列出有學生綁定的課
const courseOptions = computed(() =>
  courses.value.filter((course) => students.value.some((student) => student.courses.some((item) => item.course_id === course.id))),
)
const studentOptions = computed(() =>
  students.value.filter((student) => student.courses.some((item) => item.course_id === form.courseId)),
)

watch(
  () => form.courseId,
  () => {
    if (!studentOptions.value.some((student) => student.id === form.studentId)) form.studentId = studentOptions.value[0]?.id ?? ''
  },
)
watch([() => form.title, () => form.dueDate, () => form.description, midi, () => quiz.file, questions], () => (dirty.value = true), {
  deep: true,
})

function onMidi(event: Event) {
  midi.value = (event.target as HTMLInputElement).files?.[0] ?? null
  delete errors.midi
}

function onQuizFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  input.value = ''
  if (!file) return
  if (!/\.(pdf|txt)$/i.test(file.name)) {
    errors.quizFile = '題庫檔案請選 PDF 或 TXT。'
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    errors.quizFile = '題庫檔案最大 20 MB。'
    return
  }
  delete errors.quizFile
  quiz.file = file
}

function toggleType(value: QuizQuestionType) {
  quiz.types = quiz.types.includes(value) ? quiz.types.filter((item) => item !== value) : [...quiz.types, value]
}

function clearErrors() {
  for (const key of Object.keys(errors)) delete errors[key]
  serverError.value = ''
}

function validateAssign() {
  if (!form.courseId) errors.course = '請選擇課程。'
  if (!form.studentId) errors.student = '請選擇學生。'
  if (!form.title.trim()) errors.title = kind.value === 'quiz' ? '請填寫作業名稱。' : '請填寫作業標題。'
}

function validateSettings() {
  if (!quiz.file) errors.quizFile = '請選擇題庫檔案。'
  const count = questionCount.value
  if (!Number.isInteger(count) || count < 1 || count > 30) errors.count = '出題數量請填 1～30 題。'
  if (quiz.types.length === 0) errors.types = '請至少選一種題目類型。'
}

function jobSummary(job: QuizJob) {
  const types = job.settings.types.map((item) => QUIZ_TYPE_LABELS[item]).join('、')
  return `${job.settings.count} 題・${types}・${QUIZ_DIFFICULTY_LABELS[job.settings.difficulty]}`
}

function jobStatus(job: QuizJob) {
  if (job.status === 'running') return `出題中 ${job.progress}/${job.settings.count}`
  return JOB_STATUS[job.status] ?? job.status
}

async function loadJobs() {
  window.clearTimeout(pollTimer)
  try {
    jobs.value = await fetchQuizJobs()
  } catch {
    // 讀不到紀錄不影響其他操作，下次再試
  }
  // 還有出題中的就每 5 秒更新一次進度
  if (activeJobs.value) pollTimer = window.setTimeout(loadJobs, 5000)
}

// 「AI 生成題目並預覽」：送到背景出題，不用在這頁等
async function generate() {
  clearErrors()
  notice.value = ''
  validateSettings()
  if (Object.keys(errors).length) return
  submitting.value = true
  try {
    await createQuizJob({
      file: quiz.file!,
      count: questionCount.value,
      types: quiz.types,
      difficulty: quiz.difficulty,
      title: form.title.trim(),
      course_id: form.courseId,
      student_id: form.studentId,
      due_at: form.dueDate ? new Date(`${form.dueDate}T23:59:00`).toISOString() : null,
      use_ocr: quiz.useOcr,
    })
    notice.value = 'AI 開始出題了。完成後「作業」選單會亮起通知，可以先離開這頁，回來在「AI 出題紀錄」按「審查」。'
    quiz.file = null
    setTimeout(() => (dirty.value = false))
    await loadJobs()
    // 讓選單開始追蹤這次出題，出好時跳通知
    window.dispatchEvent(new Event('quiz-jobs-changed'))
  } catch (problem) {
    serverError.value = problem instanceof Error ? problem.message : '沒有送出，請再試一次。'
  } finally {
    submitting.value = false
  }
}

// 「審查」：讀這次出好的題目，作業名稱與指派對象帶回表單
async function review(id: string) {
  clearErrors()
  try {
    const job = await fetchQuizJob(id)
    if (job.status !== 'succeeded' || !job.questions?.length) {
      serverError.value = job.status === 'failed' ? (job.error ?? '這次出題失敗了。') : '這次出題還沒完成。'
      return
    }
    reviewing.value = job
    kind.value = 'quiz'
    if (job.title) form.title = job.title
    if (job.course_id && courseOptions.value.some((course) => course.id === job.course_id)) form.courseId = job.course_id
    if (job.student_id) setTimeout(() => (form.studentId = job.student_id ?? form.studentId))
    if (job.due_at) form.dueDate = job.due_at.slice(0, 10)
    preview.value = job.questions.map((item) => ({ ...item, answers: [...item.answers] }))
    previewIndex.value = 0
    editing.value = false
    previewing.value = true
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (problem) {
    serverError.value = problem instanceof Error ? problem.message : '讀不到這次出題。'
  }
}

// 預覽裡的「重新生成題目」：同一份教材與設定在背景再出一次
async function regenerate() {
  if (!reviewing.value) return
  try {
    await retryQuizJob(reviewing.value.id)
    previewing.value = false
    reviewing.value = null
    notice.value = 'AI 重新出題中，完成後會再通知你。'
    await loadJobs()
    window.dispatchEvent(new Event('quiz-jobs-changed'))
  } catch (problem) {
    serverError.value = problem instanceof Error ? problem.message : '沒有重新出題，請再試一次。'
  }
}

function setAnswers(answers: number[]) {
  const item = preview.value[previewIndex.value]
  if (item) item.answers = answers
}

function removeQuestion() {
  preview.value.splice(previewIndex.value, 1)
  previewIndex.value = Math.min(previewIndex.value, preview.value.length - 1)
}

function keepQuestions() {
  const bad = preview.value.findIndex((item) => (item.type === 'multiple' ? item.answers.length < 2 : item.answers.length !== 1))
  if (bad >= 0) {
    previewIndex.value = bad
    editing.value = true
    serverError.value = `第 ${bad + 1} 題的答案不完整：${preview.value[bad]?.type === 'multiple' ? '多選題至少要兩個答案' : '要選一個答案'}。`
    return
  }
  serverError.value = ''
  questions.value = preview.value
  previewing.value = false
  editing.value = false
  delete errors.questions
}

async function discard() {
  const job = discarding.value
  discarding.value = null
  if (!job) return
  try {
    await discardQuizJob(job.id)
    if (reviewing.value?.id === job.id) {
      reviewing.value = null
      questions.value = []
    }
    await loadJobs()
  } catch (problem) {
    serverError.value = problem instanceof Error ? problem.message : '沒有刪除。'
  }
}

async function save() {
  clearErrors()
  validateAssign()
  if (kind.value === 'performance') {
    if (midi.value && !/\.midi?$/i.test(midi.value.name)) errors.midi = '請選擇 .mid 或 .midi 檔。'
    if (!midi.value) errors.midi = '演奏作業需要參考 MIDI，學生錄音會跟它比對。'
  } else if (questions.value.length === 0) {
    errors.questions = '請先按「AI 生成題目並預覽」，出好後在「AI 出題紀錄」按「審查」，確認後按「儲存題目」。'
  }
  if (Object.keys(errors).length) return
  saving.value = true
  try {
    await createAssignment({
      course_id: form.courseId,
      student_id: form.studentId,
      kind: kind.value,
      title: form.title.trim(),
      description: form.description.trim(),
      due_at: form.dueDate ? new Date(`${form.dueDate}T23:59:00`).toISOString() : null,
      midi: kind.value === 'performance' ? midi.value : null,
      questions: kind.value === 'quiz' ? questions.value : undefined,
      quiz_job_id: kind.value === 'quiz' ? reviewing.value?.id : null,
    })
    reviewing.value = null
    dirty.value = false
    done.value = true
  } catch (problem) {
    serverError.value = problem instanceof Error ? problem.message : '作業沒有發布成功。'
  } finally {
    saving.value = false
  }
}

function again() {
  done.value = false
  Object.assign(form, { title: '', dueDate: '', description: '' })
  midi.value = null
  quiz.file = null
  preview.value = []
  questions.value = []
  reviewing.value = null
  loadJobs()
  if (midiInput.value) midiInput.value.value = ''
  setTimeout(() => (dirty.value = false))
}

// 設計稿的「變更資料未儲存，是否確認離開？」
const guard = useLeaveGuard(dirty)

onMounted(async () => {
  try {
    ;[courses.value, students.value] = await Promise.all([fetchMyCourses(), fetchMyStudents()])
  } catch (problem) {
    serverError.value = problem instanceof Error ? problem.message : '讀不到課程與學生。'
  }
  const wanted = typeof route.query.course === 'string' ? route.query.course : ''
  form.courseId = courseOptions.value.some((course) => course.id === wanted) ? wanted : (courseOptions.value[0]?.id ?? '')
  await loadJobs()
  // 從「AI 出題完成」通知進來（?job=）就直接打開審查
  if (typeof route.query.job === 'string') {
    kind.value = 'quiz'
    await review(route.query.job)
  } else if (route.query.tab === 'quiz') kind.value = 'quiz'
  setTimeout(() => (dirty.value = false))
})

onBeforeUnmount(() => window.clearTimeout(pollTimer))
</script>

<template>
  <!-- 有分頁（演奏／題庫）時，儲存放在分頁那一列最右邊；AI 出題結果沒有分頁，放在標題右邊 -->
  <PageHeader :title="previewing ? 'AI 出題結果' : '作業管理'">
    <button v-if="previewing" type="button" class="btn btn--primary" @click="keepQuestions">儲存</button>
  </PageHeader>

  <!-- AI 出題結果：一題一題預覽 -->
  <section v-if="previewing" class="preview">
    <div class="preview__head">
      <p class="preview__title">{{ form.title.trim() || reviewing?.source_filename.replace(/\.[^.]+$/, '') }}｜單元測驗</p>
      <span class="muted">共 {{ preview.length }} 題</span>
    </div>
    <QuizQuestionCard
      v-if="previewQuestion"
      mode="preview"
      :index="previewIndex"
      :total="preview.length"
      :type="previewQuestion.type"
      :difficulty="previewQuestion.difficulty"
      :topic="previewQuestion.topic"
      :question="previewQuestion.question"
      :options="previewQuestion.options"
      :answers="previewQuestion.answers"
      :explanation="previewQuestion.explanation"
      :hint="previewQuestion.hint"
      :editable="editing"
      @update:answers="setAnswers"
      @prev="previewIndex--"
      @next="previewIndex++"
    />
    <div v-if="previewQuestion" class="preview__edit">
      <button type="button" class="btn btn--ghost btn--small" :aria-pressed="editing" @click="editing = !editing">
        {{ editing ? '完成修改' : '修改答案' }}
      </button>
      <button type="button" class="btn btn--ghost btn--small" :disabled="preview.length <= 1" @click="removeQuestion">刪除這題</button>
    </div>
    <p v-if="preview.length < requestedCount" class="muted preview__short">
      目前 {{ preview.length }} 題（要求 {{ requestedCount }} 題；教材內容不夠或刪掉了幾題）。
    </p>
    <p v-if="serverError" class="error-text" role="alert">{{ serverError }}</p>
    <div class="preview__actions">
      <button type="button" class="btn btn--ghost btn--block" @click="regenerate">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />
        </svg>
        重新生成題目
      </button>
      <button type="button" class="btn btn--primary btn--block" @click="keepQuestions">儲存題目</button>
      <button type="button" class="btn btn--ghost btn--small preview__back" @click="previewing = false">回到設定</button>
    </div>
  </section>

  <template v-else>
    <PageToolbar divider>
      <div class="chip-group" role="tablist" aria-label="作業類型">
        <button type="button" role="tab" class="chip" :aria-pressed="kind === 'performance'" :aria-selected="kind === 'performance'" @click="kind = 'performance'">
          演奏作業上傳
        </button>
        <button type="button" role="tab" class="chip" :aria-pressed="kind === 'quiz'" :aria-selected="kind === 'quiz'" @click="kind = 'quiz'">
          題庫作業上傳
        </button>
      </div>
      <template #actions>
        <button type="submit" form="assignment-form" class="btn btn--primary" :disabled="saving || submitting">
          {{ saving ? '儲存中…' : '儲存' }}
        </button>
      </template>
    </PageToolbar>

    <div v-if="courseOptions.length === 0 && courses.length" class="card empty">
      還沒有學生綁定你的課程。學生用綁定碼加入後，才能發作業給他。
    </div>

    <form v-else id="assignment-form" class="upload" novalidate @submit.prevent="save">
      <!-- 演奏作業 -->
      <template v-if="kind === 'performance'">
        <div class="field">
          <label class="field__label" for="assignment-course">選擇課程</label>
          <select id="assignment-course" v-model="form.courseId" class="select" :aria-invalid="Boolean(errors.course)">
            <option v-for="course in courseOptions" :key="course.id" :value="course.id">{{ course.title }}</option>
          </select>
          <p v-if="errors.course" class="error-text">{{ errors.course }}</p>
        </div>
        <div class="field">
          <label class="field__label" for="assignment-student">選擇學生</label>
          <select id="assignment-student" v-model="form.studentId" class="select" :aria-invalid="Boolean(errors.student)">
            <option v-for="student in studentOptions" :key="student.id" :value="student.id">{{ student.name }}</option>
          </select>
          <p v-if="errors.student" class="error-text">{{ errors.student }}</p>
        </div>
        <div class="field">
          <label class="field__label" for="assignment-title">作業標題</label>
          <input
            id="assignment-title"
            v-model="form.title"
            class="input"
            maxlength="200"
            placeholder="例如：練習給愛麗絲第 1～16 小節"
            :aria-invalid="Boolean(errors.title)"
          />
          <p v-if="errors.title" class="error-text">{{ errors.title }}</p>
        </div>
        <div class="field">
          <label class="field__label" for="assignment-due">繳交期限</label>
          <input id="assignment-due" v-model="form.dueDate" class="input" type="date" />
          <span class="field__hint">不填就是「待定」。</span>
        </div>
        <div class="field">
          <span class="field__label">參考 MIDI</span>
          <div class="file-row">
            <span class="file-row__name">{{ midi ? midi.name : '學生錄音會跟這首曲子比對音高與節奏' }}</span>
            <label class="file-row__action">
              選擇檔案
              <input ref="midiInput" type="file" accept=".mid,.midi" class="visually-hidden" @change="onMidi" />
            </label>
          </div>
          <span class="field__hint">.mid／.midi，最大 2 MB。</span>
          <p v-if="errors.midi" class="error-text">{{ errors.midi }}</p>
        </div>
        <div class="field">
          <label class="field__label" for="assignment-description">備註（選填）</label>
          <textarea id="assignment-description" v-model="form.description" class="textarea" maxlength="2000" placeholder="想提醒學生的練習重點"></textarea>
        </div>
      </template>

      <!-- 題庫作業 -->
      <template v-else>
        <h2 class="upload__section">題庫作業上傳</h2>
        <div class="field">
          <label class="field__label" for="quiz-title">作業名稱</label>
          <input
            id="quiz-title"
            v-model="form.title"
            class="input"
            maxlength="200"
            placeholder="例如：基礎樂理"
            :aria-invalid="Boolean(errors.title)"
          />
          <p v-if="errors.title" class="error-text">{{ errors.title }}</p>
        </div>
        <div class="field">
          <span class="field__label">題庫檔案</span>
          <label class="dropzone" :class="{ 'dropzone--filled': quiz.file }">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
              <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M12 17v-6M9.5 13.5 12 11l2.5 2.5" />
            </svg>
            <strong>{{ quiz.file ? quiz.file.name : '選擇題庫檔案' }}</strong>
            <span class="muted">{{ quiz.file ? `${fileSizeText(quiz.file.size)}・點這裡換一份` : '支援 PDF、TXT 格式，最大 20 MB' }}</span>
            <input ref="quizFileInput" type="file" accept=".pdf,.txt,application/pdf,text/plain" class="visually-hidden" @change="onQuizFile" />
          </label>
          <p v-if="errors.quizFile" class="error-text">{{ errors.quizFile }}</p>
          <label class="option">
            <input v-model="quiz.useOcr" type="checkbox" /> 辨識 PDF 圖片裡的文字（OCR）
          </label>
          <p class="muted">掃描的 PDF 或圖片裡有文字時勾選，出題會比較慢。</p>
        </div>

        <h2 class="upload__section">出題設定</h2>
        <fieldset class="panel">
          <legend class="panel__legend">出題數量</legend>
          <label v-for="preset in COUNT_PRESETS" :key="preset" class="option">
            <input v-model="quiz.count" type="radio" name="quiz-count" :value="preset" /> {{ preset }} 題
          </label>
          <label class="option option--custom">
            <input v-model="quiz.count" type="radio" name="quiz-count" value="custom" /> 自訂題數
            <input
              v-model.number="quiz.customCount"
              class="input"
              type="number"
              min="1"
              max="30"
              placeholder="1～30"
              aria-label="自訂題數"
              @focus="quiz.count = 'custom'"
            />
          </label>
          <p v-if="errors.count" class="error-text">{{ errors.count }}</p>
        </fieldset>
        <fieldset class="panel">
          <legend class="panel__legend">題目類型（可複選）</legend>
          <label v-for="option in TYPE_OPTIONS" :key="option.value" class="option">
            <input type="checkbox" :checked="quiz.types.includes(option.value)" @change="toggleType(option.value)" /> {{ option.label }}
          </label>
          <p v-if="errors.types" class="error-text">{{ errors.types }}</p>
        </fieldset>
        <fieldset class="panel">
          <legend class="panel__legend">難易度</legend>
          <label v-for="option in DIFFICULTY_OPTIONS" :key="option.value" class="option">
            <input v-model="quiz.difficulty" type="radio" name="quiz-difficulty" :value="option.value" /> {{ option.label }}
          </label>
        </fieldset>

        <h2 class="upload__section">指派與繳交設定</h2>
        <fieldset class="panel">
          <div class="field">
            <label class="field__label" for="quiz-course">選擇課程</label>
            <select id="quiz-course" v-model="form.courseId" class="select" :aria-invalid="Boolean(errors.course)">
              <option v-for="course in courseOptions" :key="course.id" :value="course.id">{{ course.title }}</option>
            </select>
            <p v-if="errors.course" class="error-text">{{ errors.course }}</p>
          </div>
          <div class="field">
            <label class="field__label" for="quiz-student">選擇學生</label>
            <select id="quiz-student" v-model="form.studentId" class="select" :aria-invalid="Boolean(errors.student)">
              <option v-for="student in studentOptions" :key="student.id" :value="student.id">{{ student.name }}</option>
            </select>
            <p v-if="errors.student" class="error-text">{{ errors.student }}</p>
          </div>
          <div class="field">
            <label class="field__label" for="quiz-due">繳交期限</label>
            <input id="quiz-due" v-model="form.dueDate" class="input" type="date" />
          </div>
        </fieldset>

        <div v-if="questions.length" class="card ready" role="status">
          <span>已儲存 {{ questions.length }} 題，按「儲存作業」就會發給學生。</span>
          <button type="button" class="btn btn--ghost btn--small" @click="preview = questions; previewIndex = 0; previewing = true">再看一次</button>
        </div>
        <p v-if="errors.questions" class="error-text">{{ errors.questions }}</p>
        <p v-if="notice" class="notice" role="status">{{ notice }}</p>

        <div class="upload__buttons">
          <button type="button" class="btn btn--primary btn--block" :disabled="submitting || saving" @click="generate">
            {{ submitting ? '送出中…' : 'AI 生成題目並預覽' }}
          </button>
          <button type="submit" class="btn btn--primary btn--block" :disabled="submitting || saving">
            {{ saving ? '儲存中…' : '儲存作業' }}
          </button>
        </div>

        <section v-if="jobs.length" class="jobs" aria-labelledby="jobs-title">
          <h2 id="jobs-title" class="upload__section">AI 出題紀錄</h2>
          <article v-for="job in jobs" :key="job.id" class="job" :class="`job--${job.status}`">
            <div class="job__info">
              <strong>{{ job.title || job.source_filename }}</strong>
              <span class="muted">{{ jobSummary(job) }}・{{ formatDateTime(job.created_at) }}</span>
              <span v-if="job.status === 'failed'" class="error-text">{{ job.error }}</span>
            </div>
            <span class="badge" :class="{ 'badge--accent': job.status === 'succeeded', 'badge--warn': job.status === 'queued' || job.status === 'running', 'badge--error': job.status === 'failed' }">
              {{ jobStatus(job) }}
            </span>
            <div class="job__actions">
              <button v-if="job.status === 'succeeded'" type="button" class="btn btn--primary btn--small" @click="review(job.id)">審查</button>
              <button v-if="job.status !== 'queued' && job.status !== 'running'" type="button" class="btn btn--ghost btn--small" @click="discarding = job">刪除</button>
            </div>
          </article>
        </section>
      </template>

      <p v-if="serverError" class="error-text" role="alert">{{ serverError }}</p>
    </form>
  </template>

  <NoticeDialog
    :open="done"
    message="更新成功！"
    detail="作業已發給學生，學生在自己的「作業」頁就看得到。"
    confirm-text="確認"
    cancel-text="再發一份"
    @confirm="router.push('/teacher/practice')"
    @cancel="again"
  />
  <NoticeDialog
    :open="Boolean(discarding)"
    message="刪除這次出題？"
    detail="題目會從出題紀錄移除，之後不能再審查。"
    confirm-text="刪除"
    cancel-text="取消"
    danger
    @confirm="discard"
    @cancel="discarding = null"
  />
  <NoticeDialog
    :open="guard.asking.value"
    message="變更資料未儲存，是否確認離開？"
    confirm-text="確認"
    cancel-text="取消"
    @confirm="guard.leave"
    @cancel="guard.stay"
  />
</template>

<style scoped>
.upload {
  max-width: 720px;
}

.upload__section {
  margin: 26px 0 12px;
  padding-top: 18px;
  border-top: 1px solid var(--home-line);
  font-size: 17px;
}

.upload__section:first-child {
  margin-top: 0;
  padding-top: 0;
  border-top: 0;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  min-height: 42px;
  padding: 0 16px;
  border: 1px solid var(--home-line);
  border-radius: var(--radius-pill);
  background: #fff;
}

.file-row__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--home-muted);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-row__action {
  padding: 0;
  border: 0;
  background: none;
  color: var(--home-accent);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}

.file-row__action:hover {
  text-decoration: underline;
}

.dropzone {
  display: grid;
  justify-items: center;
  gap: 4px;
  padding: 22px 16px;
  border: 1px solid var(--home-line);
  border-radius: 22px;
  background: #fff;
  color: var(--home-ink);
  text-align: center;
  cursor: pointer;
}

.dropzone:hover,
.dropzone:focus-within {
  border-color: var(--home-accent);
}

.dropzone strong {
  font-size: 15px;
  word-break: break-all;
}

.dropzone .muted {
  font-size: 13px;
}

.dropzone--filled {
  background: var(--home-cream);
}

.panel {
  margin: 0 0 14px;
  padding: 12px 18px 14px;
  border: 1px solid var(--home-line);
  border-radius: 18px;
  background: #f7f4f0;
}

.panel__legend {
  float: left;
  width: 100%;
  margin-bottom: 6px;
  color: var(--home-muted);
  font-size: 13px;
}

.panel .field {
  clear: both;
}

.option {
  display: flex;
  align-items: center;
  gap: 10px;
  clear: both;
  padding: 6px 0;
  font-size: 14px;
  cursor: pointer;
}

.option input[type='radio'],
.option input[type='checkbox'] {
  width: 16px;
  height: 16px;
  accent-color: var(--home-accent);
}

.option--custom .input {
  width: 110px;
  min-height: 34px;
}

.ready {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 14px;
}

.upload__buttons {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}

.preview {
  max-width: 720px;
}

.preview__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin: -8px 0 14px;
}

.preview__title {
  margin: 0;
  color: var(--home-muted);
}

.preview__short {
  margin: 10px 0 0;
  font-size: 13px;
}

.preview__actions {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}

.preview__back {
  justify-self: center;
}

.preview__edit {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

.notice {
  margin: 12px 0 0;
  color: var(--home-accent-dark);
  font-size: 14px;
}

.jobs {
  margin-top: 8px;
}

.job {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 16px;
  border: 1px solid var(--home-line);
  border-radius: 18px;
  background: #fff;
}

.job + .job {
  margin-top: 10px;
}

.job--succeeded {
  border-color: var(--home-accent);
}

.job__info {
  display: grid;
  flex: 1 1 260px;
  gap: 2px;
  min-width: 0;
  font-size: 14px;
}

.job__info .muted {
  font-size: 13px;
}

.job__info .error-text {
  margin: 0;
  font-size: 13px;
}

.job__actions {
  display: flex;
  gap: 8px;
}
</style>
