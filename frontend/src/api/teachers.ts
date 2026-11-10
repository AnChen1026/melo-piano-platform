import { apiUrl, request } from './http'
import type { TeacherCardData } from '@/mocks/home'

interface FeaturedTeacherResponse {
  id: string
  name: string
  specialty: string | null
  bio: string | null
  photo_url: string | null
}

// 首頁「認識老師」：資料庫裡有已發布課程的老師，有照片的優先，其餘隨機
export async function fetchFeaturedTeachers(limit = 4): Promise<TeacherCardData[]> {
  const teachers = await request<FeaturedTeacherResponse[]>('/api/teachers/featured', { query: { limit } })
  return teachers.map((teacher) => ({
    id: teacher.id,
    name: teacher.name,
    specialty: teacher.specialty,
    bio: teacher.bio,
    photo: teacher.photo_url ? apiUrl(teacher.photo_url) : null,
  }))
}
