import { apiUrl, request } from './http'
import type { TeacherCardData } from '@/mocks/home'
import sampleFemale1 from '@/assets/images/女老師1.png'
import sampleMale1 from '@/assets/images/男老師1.png'
import sampleFemale2 from '@/assets/images/女老師2.png'
import sampleMale2 from '@/assets/images/男老師2.png'

// 老師還沒上傳照片時輪流使用的示範照片（原本首頁展示用的四張）
const SAMPLE_PHOTOS = [sampleFemale1, sampleMale1, sampleFemale2, sampleMale2]

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
  return teachers.map((teacher, index) => ({
    id: teacher.id,
    name: teacher.name,
    specialty: teacher.specialty,
    bio: teacher.bio,
    photo: teacher.photo_url ? apiUrl(teacher.photo_url) : SAMPLE_PHOTOS[index % SAMPLE_PHOTOS.length]!,
    isSamplePhoto: !teacher.photo_url,
  }))
}
