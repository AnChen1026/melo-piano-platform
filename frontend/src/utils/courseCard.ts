import type { CourseSummary } from '@/types/course'
import type { CourseCardData } from '@/mocks/home'

// 首頁與全部課程頁共用：把後端課程轉成課程卡需要的欄位

// 線上實體皆可的課：篩選線上或實體時都要算進去
export const HYBRID_LABEL = '線上實體皆可'

export function deliveryLabel(mode: string | null): string {
  if (mode === 'online' || mode === '線上') return '線上'
  if (mode === 'in_person' || mode === '實體') return '實體'
  if (mode === 'hybrid') return HYBRID_LABEL
  return '未填'
}

export function toCourseCard(course: CourseSummary): CourseCardData {
  const summary =
    course.description || [course.region, course.timeSlots].filter((item): item is string => Boolean(item)).join(' · ')
  return {
    id: course.id,
    title: course.title,
    category: course.style || '鋼琴課',
    teacherName: course.teacherName || '未填老師',
    cover: course.imageUrl,
    level: course.level || '未填',
    format: deliveryLabel(course.deliveryMode),
    minutes: course.durationMinutes,
    price: course.pricePerLesson,
    summary,
    region: course.region,
    timeSlots: course.timeSlots,
    description: course.description,
    teacherPhoto: course.teacherPhotoUrl,
  }
}
