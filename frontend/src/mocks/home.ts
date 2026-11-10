import classicalCover from '@/assets/images/古典鋼琴.png'
import studioFemale from '@/assets/images/女老師3.png'
import studioMale from '@/assets/images/男老師3.png'

// 找課程度只有這幾種，和 GLOSSARY 的「找課程度」一致
export type CourseLevel = '入門' | '初階' | '中階' | '進階'

// 首頁「認識老師」：資料來自 GET /api/teachers/featured，不是寫死的文案
export interface TeacherCardData {
  id: string
  name: string
  specialty: string | null
  bio: string | null
  photo: string
  // 老師還沒上傳照片，用的是示範照片，不是本人
  isSamplePhoto: boolean
}

export interface CourseCardData {
  id: string
  title: string
  category: string
  teacherName: string
  cover: string | null
  level: string
  format: string
  minutes: number | null
  price: number | null
  summary: string
  region: string | null
  timeSlots: string | null
  description: string | null
  teacherPhoto: string | null
}

export interface HighlightItem {
  title: string
  text: string
}

export interface FlowStep {
  title: string
  tag: string
  text: string
}

export interface FaqItem {
  question: string
  answer: string
}

// 關於我們、上課流程與常見問題是首頁文案。課程清單和老師介紹由資料庫提供。
export const courseLevels: CourseLevel[] = ['入門', '初階', '中階', '進階']

export const aboutPhotos = [
  { src: studioFemale, alt: '老師在琴房裡示範' },
  { src: classicalCover, alt: '陽光下的平台鋼琴' },
  { src: studioMale, alt: '老師坐在鋼琴前' },
]

// 下面的文字依照 PRD 與 User Flow 的流程撰寫
export const highlights: HighlightItem[] = [
  {
    title: '找到喜歡的鋼琴課',
    text: '從古典、流行到爵士，依照自己的興趣與程度，探索適合的課程與老師',
  },
  {
    title: '先聊聊，再決定',
    text: '有興趣就先向老師聯繫，了解教學方式與上課安排，找到適合自己的學習步調',
  },
  {
    title: '開始屬於你的音樂旅程',
    text: '與老師一起展開學習，透過課程安排與練習回饋，讓每一次練習都更有方向',
  },
]

export const studentSteps: FlowStep[] = [
  { title: '找到適合自己的鋼琴課', tag: '免登入', text: '分享你喜歡的音樂風格與學習目標，讓 Melo 為你推薦合適的老師與課程。' },
  { title: '先和老師聊聊', tag: '需登入', text: '遇到感興趣的課程，可以先向老師洽詢，了解教學方式與上課安排。' },
  { title: '建立師生關係', tag: '雙方確認', text: '確認彼此的上課意願後，透過老師提供的綁定碼，完成師生關係確認。' },
  { title: '安排你的上課時間', tag: '加入課程後', text: '隨時查看個人課表，也能提出約課、請假或調課申請，由老師確認後更新安排。' },
  { title: '練習，讓進步看得見', tag: '開始學習後', text: '跟著老師的練習作業錄音，透過音高、節奏分析與回饋，找到下一次進步的方向。' },
]

export const teacherSteps: FlowStep[] = [
  { title: '分享你的鋼琴課程', tag: '審核通過後', text: '設定課程風格、適合程度與授課方式，讓正在尋找鋼琴老師的學生更容易認識你。' },
  { title: '認識你的新學生', tag: '課程洽詢', text: '透過課程洽詢了解學生的學習目標與期待，確認彼此意願後，開啟一段新的教學旅程。' },
  { title: '為學生安排練習', tag: '加入課程後', text: '依照學習進度指定練習曲目，搭配錄音分析與回饋，幫助學生找到進步的方向。' },
  { title: '課前掌握學習狀況', tag: '上課前', text: '快速了解學生近期的練習表現與需要加強的地方，讓每一次備課都更有方向。' },
  { title: '讓 AI 成為教學助手', tag: 'AI 輔助', text: '上傳教材，由 AI 協助產生測驗題目，確認內容後即可發布，讓學生透過練習與測驗加深理解。' },
]

export const faqs: FaqItem[] = [
  {
    question: '不登入也能找課嗎？',
    answer: '可以。描述想學的內容就能看到推薦，想洽詢老師時再註冊或登入即可。',
  },
  {
    question: '綁定碼是什麼？',
    answer: '老師發給你一個人、只對應一門課的上課資格。輸入後才會開啟這門課的課表和練習，不能轉給別人使用。',
  },
  {
    question: '可以同時問好幾位老師嗎？',
    answer: '可以。每一門課各有一段對話，彼此分開，綁定之後也會沿用同一段對話。',
  },
  {
    question: '沒有麥克風怎麼錄音？',
    answer: '可以把錄好的音檔上傳，一樣會和老師指定的曲子比對。',
  },
  {
    question: '練習的分數會影響我的程度嗎？',
    answer: '不會。練習回饋只描述那一次錄音，不會改變你找課時的程度。',
  },
]
