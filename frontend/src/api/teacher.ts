import { apiUrl, request } from './http'
import type {
  Assignment,
  QuizAttempt,
  QuizDifficulty,
  QuizDraftQuestion,
  QuizJob,
  QuizQuestion,
  QuizQuestionType,
  BoundStudent,
  Conversation,
  Course,
  CourseInput,
  CourseJoinCode,
  LessonSummary,
  Message,
  Studio,
  StudioInput,
  RecurringLesson,
  RecurringLessonResult,
  WeeklyWindow,
  TeacherAvailabilitySlot,
  TeacherChangeRequest,
  TeacherLesson,
  TeacherProfile,
  TeacherProfileInput,
  TeacherRecording,
} from '@/types/api'

// ---------- 個人資料
export const fetchTeacherProfile = () => request<TeacherProfile>('/teacher/me')
export const saveTeacherProfile = (input: TeacherProfileInput) =>
  request<TeacherProfile>('/teacher/profile', { method: 'POST', body: { ...input } })

export function uploadTeacherPhoto(file: File) {
  const form = new FormData()
  form.append('photo', file)
  return request<TeacherProfile>('/teacher/photo', { method: 'POST', body: form })
}

// ---------- 工作室：審核通過後老師自己填寫，編號由系統產生
export const fetchStudio = () => request<Studio | null>('/teacher/studio')
export const saveStudio = (input: StudioInput) => request<Studio>('/teacher/studio', { method: 'PUT', body: { ...input } })

// ---------- 課程
export const fetchMyCourses = () => request<Course[]>('/teacher/courses')
export const fetchCourse = (id: string) => request<Course>(`/courses/${id}`)
export const createCourse = (input: CourseInput) => request<Course>('/courses', { method: 'POST', body: { ...input } })
export const updateCourse = (id: string, input: Partial<CourseInput>) =>
  request<Course>(`/courses/${id}`, { method: 'PATCH', body: { ...input } })

export function uploadCourseImage(id: string, file: File) {
  const form = new FormData()
  form.append('image', file)
  return request<Course>(`/courses/${id}/image`, { method: 'POST', body: form })
}

// 課程的限時綁定碼：期限內拿到碼的學生都能加入，一門課同時只有一組
export const fetchJoinCode = (courseId: string) => request<CourseJoinCode | null>(`/teacher/courses/${courseId}/join-code`)
export const createJoinCode = (courseId: string, hours: number) =>
  request<CourseJoinCode>(`/teacher/courses/${courseId}/join-code`, { method: 'POST', body: { hours } })
export const deleteJoinCode = (courseId: string) => request(`/teacher/courses/${courseId}/join-code`, { method: 'DELETE' })


// ---------- 學生
export const fetchMyStudents = () => request<BoundStudent[]>('/teacher/students')
export const unbindStudent = (courseId: string, studentId: string) =>
  request(`/teacher/courses/${courseId}/students/${studentId}/unbind`, { method: 'POST' })

// ---------- 課表與課務申請
export const fetchMyLessons = () => request<TeacherLesson[]>('/teacher/lessons')
export const fetchLessonSummary = (lessonId: string) => request<LessonSummary>(`/teacher/lessons/${lessonId}/summary`)
export interface TeacherLessonInput {
  student_id: string
  course_id: string
  starts_at: string
  ends_at: string
  slot_id?: string | null
}
// 和學生約好了，直接排進正式課表（從時段拖過來時帶 slot_id）
export const createTeacherLesson = (input: TeacherLessonInput) =>
  request<TeacherLesson>('/teacher/lessons', { method: 'POST', body: { ...input } })
export const cancelTeacherLesson = (lessonId: string) =>
  request<TeacherLesson>(`/teacher/lessons/${lessonId}/cancel`, { method: 'POST' })

// ---------- 可上課時段
export const fetchMySlots = () => request<TeacherAvailabilitySlot[]>('/teacher/availability')
export const createSlot = (startsAt: string, endsAt: string) =>
  request<TeacherAvailabilitySlot>('/teacher/availability', { method: 'POST', body: { starts_at: startsAt, ends_at: endsAt } })
export const moveSlot = (id: string, startsAt: string, endsAt: string) =>
  request<TeacherAvailabilitySlot>(`/teacher/availability/${id}`, {
    method: 'PATCH',
    body: { starts_at: startsAt, ends_at: endsAt },
  })
export const deleteSlot = (id: string) => request<void>(`/teacher/availability/${id}`, { method: 'DELETE' })
// 取消預約：待確認的約課退回、已排的課取消，時段回到可預約
export const releaseSlot = (id: string) =>
  request<TeacherAvailabilitySlot>(`/teacher/availability/${id}/release`, { method: 'POST' })

// 每週固定可上課時間：整份換掉，還沒人預約的固定時段會重算
export const fetchWeeklyAvailability = () => request<WeeklyWindow[]>('/teacher/availability/weekly')
export const saveWeeklyAvailability = (windows: WeeklyWindow[]) =>
  request<WeeklyWindow[]>('/teacher/availability/weekly', { method: 'PUT', body: { windows } })

// 學生的固定上課時間：已排的課只有勾選的才一起改或取消
export const fetchRecurringLessons = () => request<RecurringLesson[]>('/teacher/recurring-lessons')
export const createRecurringLesson = (input: WeeklyWindow & { student_id: string; course_id: string }) =>
  request<RecurringLessonResult>('/teacher/recurring-lessons', { method: 'POST', body: { ...input } })
export const updateRecurringLesson = (id: string, input: WeeklyWindow & { move_lesson_ids: string[] }) =>
  request<RecurringLessonResult>(`/teacher/recurring-lessons/${id}`, { method: 'PATCH', body: { ...input } })
export const stopRecurringLesson = (id: string, cancelLessonIds: string[]) =>
  request<void>(`/teacher/recurring-lessons/${id}/stop`, { method: 'POST', body: { cancel_lesson_ids: cancelLessonIds } })

export const fetchChangeRequests = (status: 'pending' | 'all' = 'pending') =>
  request<TeacherChangeRequest[]>('/teacher/change-requests', { query: { status } })
export const decideChangeRequest = (id: string, approve: boolean) =>
  request<{ id: string; status: string }>(`/teacher/change-requests/${id}/decision`, { method: 'POST', body: { approve } })

// ---------- 練習錄音
export const fetchCourseRecordings = (courseId: string) =>
  request<TeacherRecording[]>(`/teacher/courses/${courseId}/recordings`)

// ---------- 聊天
export const fetchTeacherConversations = () => request<Conversation[]>('/teacher/conversations')
export const fetchTeacherConversation = (id: string) => request<Conversation>(`/teacher/conversations/${id}`)
export const fetchTeacherMessages = (id: string) => request<Message[]>(`/teacher/conversations/${id}/messages`)
export const sendTeacherMessage = (id: string, body: string, clientMessageId: string) =>
  request<Message>(`/teacher/conversations/${id}/messages`, {
    method: 'POST',
    body: { body, client_message_id: clientMessageId },
  })
export const issueBindingCode = (id: string) =>
  request<{ code: string }>(`/teacher/conversations/${id}/binding-code`, { method: 'POST' })

// ---------- 作業：替已綁定的學生發作業，附參考 MIDI 與教材
export interface AssignmentInput {
  course_id: string
  student_id: string
  kind: Assignment['kind']
  title: string
  description?: string
  due_at?: string | null
  midi?: File | null
  materials?: File[]
  // 練習速度（BPM），沒填就用 MIDI 的速度
  practice_bpm?: number | null
  // 題庫作業：AI 出題後老師審查（可能改過答案）的題目，以及是哪一次出題
  questions?: QuizDraftQuestion[]
  quiz_job_id?: string | null
}

export const fetchAssignments = () => request<Assignment[]>('/teacher/assignments')
export const deleteAssignment = (id: string) => request<void>(`/teacher/assignments/${id}`, { method: 'DELETE' })

export function createAssignment(input: AssignmentInput) {
  const form = new FormData()
  form.append('course_id', input.course_id)
  form.append('student_id', input.student_id)
  form.append('kind', input.kind)
  form.append('title', input.title)
  if (input.description) form.append('description', input.description)
  if (input.due_at) form.append('due_at', input.due_at)
  if (input.midi) form.append('midi', input.midi)
  if (input.practice_bpm) form.append('practice_bpm', String(input.practice_bpm))
  for (const file of input.materials ?? []) form.append('materials', file)
  if (input.questions?.length) form.append('questions', JSON.stringify(input.questions))
  if (input.quiz_job_id) form.append('quiz_job_id', input.quiz_job_id)
  return request<Assignment>('/teacher/assignments', { method: 'POST', body: form })
}

// ---------- 題庫作業：上傳教材請 AI 在背景出題，完成後老師審查再發作業
export interface QuizJobInput {
  file: File
  count: number
  types: QuizQuestionType[]
  difficulty: QuizDifficulty
  // 作業名稱與指派對象可以先帶著，審查完直接發
  title?: string
  course_id?: string
  student_id?: string
  due_at?: string | null
  // 辨識 PDF 裡的圖片文字（掃描檔要勾）
  use_ocr?: boolean
}

export function createQuizJob(input: QuizJobInput) {
  const form = new FormData()
  form.append('file', input.file)
  form.append('count', String(input.count))
  form.append('types', input.types.join(','))
  form.append('difficulty', input.difficulty)
  if (input.title) form.append('title', input.title)
  if (input.course_id) form.append('course_id', input.course_id)
  if (input.student_id) form.append('student_id', input.student_id)
  if (input.due_at) form.append('due_at', input.due_at)
  if (input.use_ocr) form.append('use_ocr', 'true')
  return request<QuizJob>('/teacher/quiz/jobs', { method: 'POST', body: form })
}

export const fetchQuizJobs = () => request<QuizJob[]>('/teacher/quiz/jobs')
export const fetchQuizJob = (id: string) => request<QuizJob>(`/teacher/quiz/jobs/${id}`)
export const retryQuizJob = (id: string) => request<QuizJob>(`/teacher/quiz/jobs/${id}/retry`, { method: 'POST' })
export const discardQuizJob = (id: string) => request<void>(`/teacher/quiz/jobs/${id}`, { method: 'DELETE' })

export const fetchAssignmentQuiz = (id: string) => request<QuizQuestion[]>(`/teacher/assignments/${id}/quiz`)
export const fetchAssignmentQuizAttempts = (id: string) => request<QuizAttempt[]>(`/teacher/assignments/${id}/quiz/attempts`)

export const teacherAssignmentMidiUrl = (id: string) => apiUrl(`/teacher/assignments/${id}/midi`)
export const teacherMaterialUrl = (id: string) => apiUrl(`/teacher/assignment-materials/${id}`)
export const teacherScoreSheetUrl = (recordingId: string) => apiUrl(`/teacher/recordings/${recordingId}/score-sheet`)
