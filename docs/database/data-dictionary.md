# 資料庫資料字典

## 小白版心智模型

資料由網頁進入 PostgreSQL 時，依序經過：

1. FastAPI Router 接收請求。
2. Service 驗證權限與商業規則。
3. SQLAlchemy Model 把 Python 物件轉成 SQL。
4. PostgreSQL 保存資料並執行外鍵、唯一值與檢查限制。

`backend/models/*.py` 是目前資料表的 Python 對照；`backend/alembic/versions/*.py` 是資料庫從舊版走到新版的正式紀錄。所有正式資料表由 Alembic 建立，應用程式啟動時不使用 `create_all()`。

## Migration 版本鏈

```text
001 users
  → 002 teacher applications / auth identities
  → 003 optional teacher proof
  → 004 student learning
  → 005 unify courses
  → 006 message client id
  → 007 teacher tables
  → 008 lesson preparation summaries
  → 009 images / optional teacher profile
  → 010 reference MIDI metadata
  → 011 recommendation sessions / items
  → 012 password reset requests
  → 013 assignments / support chat
  → 014 course join codes
  → 015 studios
  → 016_storage_cleanup ─┐
  → 016_metronome_score ─┼→ 017_merge_storage_audio ─┐
       └→ 017_availability_slots ────────────────────┴→ 018_merge_availability_storage
  → 019 weekly schedule
  → 020 course embeddings
```

`015` 之後有兩次分支，由 `017_merge_storage_audio` 與 `018_merge_availability_storage` 合併。目前只有一個 head：`025_course_chat_starters`。所有資料表的用途見 `docs/資料表設計.md`，這裡只寫需要細節的表。

## `recommendation_sessions`

一筆代表訪客在首頁的一次找課對談。它保存訪客已說的話、已確認條件、追問次數與目前狀態。瀏覽器 Cookie 中的隨機識別值會先做 SHA-256，資料庫只保存雜湊後的 `owner_hash`；同一段對談 24 小時後失效。

| 欄位 | 可空 | 說明 |
| --- | --- | --- |
| `id` | 否 | UUID 主鍵，也是前端回答與讀取時使用的 session ID |
| `owner_hash` | 否 | 瀏覽器擁有者識別值的 SHA-256 |
| `messages` | 否 | 本次訪客與助理訊息的 JSON 陣列 |
| `criteria` | 否 | 程度、曲風、方式、地區、預算與時段；未知保持 `null` |
| `asked_fields` | 否 | 已經追問過的欄位，避免重複詢問 |
| `question_count` | 否 | 已追問題數，資料庫限制為 0 到 2 |
| `status` | 否 | `asking`、`done` 或 `unsupported` |
| `question` | 是 | 目前等待訪客回答的題目 |
| `result_message` | 否 | 畫面顯示的結果說明 |
| `expires_at` | 否 | 對談失效時間 |

## `recommendation_items`

一筆代表某次首頁推薦中的一門課。`course_id` 必須指向正式 `courses`，所以系統不能保存虛構課程；同一次推薦中，同一門課及同一顯示順位都不能重複。讀取結果時仍會再次檢查課程為 `published`，老師後來封存的課程不再顯示。

| 欄位 | 可空 | 說明 |
| --- | --- | --- |
| `id` | 否 | UUID 主鍵 |
| `session_id` | 否 | 所屬找課對談；刪除對談時一併刪除 |
| `course_id` | 否 | 正式課程外鍵；刪除課程時一併刪除 |
| `position` | 否 | 在本次結果中的順序 |
| `matched` | 否 | 實際符合的條件名稱 |
| `unknown` | 否 | 課程未填且訪客也未指定的欄位名稱 |
| `reason` | 否 | 只由實際命中欄位組成的推薦原因 |

## `courses` 與參考 MIDI

`courses` 是課程的權威資料表。每門課只能由自己的老師管理，狀態為 `draft`、`published` 或 `archived`；只有 `published` 可以公開顯示及建立接洽。

過渡期間，`courses.reference_midi_path` 繼續供課程 MIDI 下載，以及作業沒有 MIDI 時的評分讀取。課程 MIDI 新上傳同時寫入這個欄位及 `reference_midis`。演奏作業的 MIDI 存在 `assignments.midi_path`，不經過 `reference_midis`。

## `reference_midis`

一筆代表一門課目前使用的參考 MIDI。資料庫保存 metadata，MIDI 內容本機放 `uploads/midi/`，共用測試站放 Supabase 私有 bucket。

| 欄位 | 可空 | 說明 |
| --- | --- | --- |
| `id` | 否 | UUID 主鍵 |
| `course_id` | 否 | 所屬課程；一門課最多一筆 |
| `teacher_id` | 否 | 所屬老師帳號 |
| `storage_key` | 否 | 檔案儲存位置 |
| `original_filename` | 否 | 上傳時的安全檔名 |
| `content_sha256` | 是 | 檔案內容 SHA-256；舊資料回填時可能沒有 |
| `file_size_bytes` | 是 | 檔案大小；舊資料回填時可能沒有 |
| `created_at` | 否 | metadata 建立時間 |
| `updated_at` | 否 | metadata 最後更新時間 |

約束與索引：

- `uq_reference_midis_course_id`：一門課只有一筆目前版本。
- `ck_reference_midis_file_size_nonnegative`：檔案大小不能是負數。
- `fk_reference_midis_course_id_courses`：課程不存在時不能建立；實體刪除課程會連動刪除 metadata。
- `fk_reference_midis_teacher_id_users`：老師帳號必須存在。
- `ix_reference_midis_teacher_course`：加速老師依課程查詢。

過渡規則：

- 010 會回填非空白的 `courses.reference_midi_path`。
- 舊資料沒有原始內容可重新計算，因此 SHA-256 與大小可以是 NULL。
- 新上傳會計算 SHA-256、大小並同步更新新舊兩處。
- 更換 MIDI 更新同一筆 metadata；舊檔案暫時保留，讓已評分錄音仍可追溯原曲。
- 010 降級只刪除 metadata 表，不清除舊路徑。

## `lesson_preparation_summaries`

課前摘要沿用 Alembic 008 建立的 `lesson_preparation_summaries`。一筆摘要只屬於一堂正式課、同一位老師、同一門課與同一位學生。來源範圍為上一堂結束到這一堂開始；沒有平台紀錄時必須明確說明，不推論成學生沒有練習。

本次整合不建立第二套 `lesson_summaries`。

## 後續 Contract 階段

只有在下列條件都完成後，才能移除 `courses.reference_midi_path`：

1. 老師與學生下載端改讀 `reference_midis.storage_key`。
2. 新練習錄音能固定記住當次使用的 MIDI 版本或不可變 storage key。
3. 音訊評分與課前摘要不再讀舊欄位。
4. 正式資料完成筆數與路徑比對。
5. 已完成備份及還原演練。

## `course_embeddings`

**已由 `rag_documents` 取代（`024`），保留一個版本後刪除，程式不再讀寫。**

一門課一筆語意向量，只用來排序已篩好的已發布課程。課程事實仍以 `courses` 為準。

| 欄位 | 可空 | 說明 |
| --- | --- | --- |
| `course_id` | 否 | 所屬課程 |
| `model_version` | 否 | 模型 digest。和設定不同時向量不使用 |
| `content_hash` | 否 | 課程內容雜湊。課程編輯後舊向量失效，需重跑索引工具 |
| `embedding` | 否 | 向量（JSONB） |
| `updated_at` | 否 | 更新時間 |

## `rag_documents`

AI 找課檢索用的 pgvector 向量（`024_pgvector_rag`）。課程一門一筆（不切塊）；`source_type = 'platform_guide'` 預留給平台說明，目前沒有使用。課程事實仍以 `courses` 為準。

| 欄位 | 可空 | 說明 |
| --- | --- | --- |
| `source_type` | 否 | `course` 或 `platform_guide`，和下面兩欄的組合由 check constraint 限制 |
| `course_id` | 是 | 課程（`course` 時必填，課程刪除時一起刪） |
| `source_key` | 是 | 平台說明的代號（`platform_guide` 時必填） |
| `chunk_index` | 否 | 切塊序號，目前都是 0 |
| `title`、`content` | 否 | 建向量用的文字 |
| `content_hash` | 否 | 內容雜湊。課程編輯後舊向量失效，需重跑 `scripts.index_course_embeddings` |
| `model_version` | 否 | bge-m3 的 digest，和設定不同時不使用 |
| `embedding` | 否 | `extensions.vector(1024)`，HNSW 餘弦索引 `ix_rag_documents_embedding` |
| `updated_at` | 否 | 更新時間 |

## `course_chat_starters`

AI 找課的推薦開場問題（`025`）。由 `scripts.chat_starters` 從 `scripts/data/chat_starters.json` 匯入，並用網站的檢索驗證；沒通過的 `is_active = false`。

| 欄位 | 可空 | 說明 |
| --- | --- | --- |
| `text` | 否 | 問題文字，唯一 |
| `category` | 否 | `course_search`、`criteria`、`platform_howto`，API 每類隨機挑一句 |
| `is_active` | 否 | 驗證通過才為 true |
| `verified_at`、`verified_model_version`、`top_score` | 是 | 最近一次驗證的時間、模型版本與最高相似度 |
| `check_note` | 否 | 驗證結果說明 |

## `storage_cleanup_jobs`

雲端檔案刪除失敗時記下 `storage_key` 與 `attempts`，由 `python -m scripts.retry_storage_cleanup` 重試，成功後移除。

## 資料治理待辦

- 正式環境的檔案儲存要有權限、版本、備份及生命週期政策（共用測試站已用 Supabase 私有 bucket）。
- 把共用測試站的備份從單一維運電腦移到常駐主機，並保存第二份副本（現況見 `docs/operations.md`）。
- 分開應用程式、Migration 與唯讀分析帳號。
- 定義個資保存期限、使用者刪除與操作稽核政策。
- 在後續 Migration 強化老師、課程與學生的複合歸屬一致性。
