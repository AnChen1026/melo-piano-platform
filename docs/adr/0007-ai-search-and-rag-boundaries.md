# 正式搜尋、推薦與 RAG 共用產品主線及課程來源

正式使用者介面沿用 Vue，後端沿用 FastAPI、Session Cookie、SQLAlchemy、Alembic 與主要 PostgreSQL。正式課程的唯一來源是 `courses`；公開搜尋與首頁推薦只可回傳狀態為 `published` 的課程。

`feature/AICourseFinder` 定位為已凍結的研究原型。其 Next.js 畫面、獨立 `AI_DATABASE_URL`、另一套 Migration 與假課程資料表不進入正式產品，也不作為合併後的開發基底。可採用的演算法必須從最新 `main` 建立新分支，逐項改接正式資料與測試後再合併。

課程搜尋、首頁推薦與 RAG 分開負責：搜尋查詢正式課程欄位；推薦根據訪客明確提供的條件排序正式課程；RAG 只根據經核准、可追蹤版本的知識文件產生附來源的回答。RAG 不建立課程，不改寫課程事實，也不在缺少資料時猜測答案。

未來 AI 搜尋或 RAG 的正式開發都從當時最新 `main` 開始。若新增資料表，Migration 必須接在合併當下唯一的 Alembic head，並在同一個 Pull Request 提供資料來源、保存期限、權限、失敗處理與可重做的驗證結果。

首頁 AI 找課後來改成根據檢索到的課程聊天回答，推薦說明改由模型撰寫，見 [0011](0011-ai-course-chat.md)。
