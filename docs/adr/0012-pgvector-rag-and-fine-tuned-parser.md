# AI 找課改用 pgvector 檢索、校準門檻，需求解析交給微調模型

[0011](0011-ai-course-chat.md) 把 AI 找課改成聊天顧問後，留下幾個問題：向量存在 JSONB、在 Python 逐筆計算；沒有門檻，無關的話也會附上課程；曲風被當成硬條件篩選（「兒童鋼琴檢定」只篩出兒童入門課）；規則解析看不懂「一千二」「下班後」這類說法。這次一起處理，數字與實驗紀錄在 [docs/ai-course-finder/開發紀錄.md](../ai-course-finder/開發紀錄.md)。

**向量存進 pgvector，擴充功能放在 `extensions` schema。** 新表 `rag_documents`（migration 024）的向量欄位是 `extensions.vector(1024)`，加上 HNSW 餘弦索引。Supabase 本來就把擴充功能放在 `extensions`，本機也照做；程式寫完整名稱（`OPERATOR(extensions.<=>)`），不依賴各環境的 search_path。資料庫、CI、備份與還原工具都改用 `pgvector/pgvector:0.8.1-pg17-trixie`（和原本的 `postgres:17` 同版本、同系統）；還原前先建擴充功能。條件篩過的候選課程精確計算相似度，不經過近似索引，避免漏掉符合條件的課。課程一門一筆，不切塊：介紹最長 1000 字，在 bge-m3 的長度內。`course_embeddings` 保留一個版本後再刪。

**門檻 0.574，只在學生沒說條件時使用。** 門檻在 210 句標註查詢的 dev 集上校準：選「正常查詢至少保留 98%」的最高門檻。bge-m3 在這份課程上，無關查詢的最高相似度也有 0.66，和正常查詢重疊，所以門檻只擋明顯無關的話，剩下的交給意圖判斷與提示詞。學生說了地區、預算等條件時，照條件篩出的課就是答案，不套門檻。被擋下時告訴模型「先了解需求」，不能說平台沒有課。交給模型的課程數維持 6（Recall@6 約 98%）；多輪對話合併最近三句做查詢。

**上課方式沒填的課不排除。** 示範資料把「線上／實體皆可」存成空值；篩選時空值也當作符合，卡片提醒向老師確認。卡片也核對上課方式：和學生要的不同時紅字提醒，因為實測時模型會把實體課說成線上。

**需求解析交給 QLoRA 微調的千問 4B，失敗就退回規則。** 模型讀最近幾句對話，輸出意圖（找課／平台使用／無關）、五個硬條件（程度、上課方式、地區、預算、時段）與檢索主題 `search_query`。曲風不再當硬條件，改放進檢索主題做語意比對。規格與提示詞在 `backend/course_parser_spec.py`，訓練與網站共用同一份。設定 `COURSE_PARSER_LLM_MODEL` 才啟用，模型要在閘道的 `AI_GATEWAY_CHAT_MODELS` 開放；沒設定、閘道沒開或輸出不合規格時，改用原本的 `parse_criteria`，網站照常運作。只微調需求解析，不微調聊天回覆：前者答案明確、能量化，後者要大量人工審查。呼叫時不加 `response_format: json_object`：Ollama 的 JSON 限制解碼擋掉模型學到的第一個 token，微調模型因此多輸出欄位，合格率掉到 0%；不加時合格率 100%，格式交給 `parse_output` 嚴格檢查。訓練用 MLX 4-bit、上線用 Ollama int4，轉檔後要用上線的呼叫方式重新驗收（`scripts/qlora/evaluate_ollama.py`）。

**微調模型發布成 GGUF，放在 Hugging Face。**（2026-11-10 補充）Ollama 從 safetensors 匯入的 int4 模型用 MLX 引擎，只有 Apple Silicon Mac 能跑，組員的 Windows 電腦不行。Ollama 0.40 也已經不支援 `ADAPTER`，沒辦法只發 5 MB 的 LoRA 讓大家掛在官方千問上。2.5 GB 的模型超過 GitHub 單一檔案和 Release 附件的上限，所以改用 llama.cpp 轉成 GGUF Q4_K_M（`scripts/qlora/export_gguf.py`），公開放在 `hf.co/Ollie12304/melo-qwen3-4b-ft`。組員用 `ollama pull` 下載，再用 `ollama cp` 改成 `melo-qwen3-4b-ft`，後端設定不必改。HF repo 附上官方千問 instruct 的 Go 模板，不然 Ollama 會套用思考版模板，回覆前多出 `</think>`。

**推薦問題存資料庫，用網站的檢索驗證。** `course_chat_starters`（migration 025）存 30 句人工審過的開場問題與每句的驗證結果；`scripts/chat_starters.py` 用網站實際的檢索跑過，沒過的自動停用。API 從找課、條件組合、平台使用三類各挑一句。課程或索引改過要重跑驗證。
