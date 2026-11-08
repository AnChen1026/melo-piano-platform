# AI 找課改造計畫：QLoRA 微調、pgvector RAG、聊天式找課、推薦問題

> 狀態：**已確認，實作中**（2026-11-09）　P0 ✅　P1 ✅（雲端待部署）　P2 ✅　P3 ✅　P4 ✅　P5 ✅　P6 ✅（共用閘道待管理員開放模型）　P7 進行中
> 開發紀錄：[docs/ai-course-finder/開發紀錄.md](../../ai-course-finder/開發紀錄.md)
> 分支：`feature/ai-course-rag-qlora`（從 `main` b94fc26 開出，已含 PR #48）
> 參考：
> - [chinese-cold-joke-chatbot](https://github.com/OllieHu12304/chinese-cold-joke-chatbot)：QLoRA 流程（編號腳本、分組切分、只算回答 loss、用驗證集選權重、測試集不參與選擇）
> - [health-news-rag-assistant](https://github.com/OllieHu12304/health-news-rag-assistant)：RAG 流程（摘要建索引、L2 正規化、門檻 0.83、Top-3、追問時合併上一題、來源由程式附上）
> - [PR #48](https://github.com/AnChen1026/melo-piano-platform/pull/48)（已合併）：AI 找課改成聊天式顧問，`/api/course-chat`

---

## 0. 目標與現況

### 要解決的問題（對照附表）

| 問題 | 現況 | 這次的做法 |
|---|---|---|
| **幻覺** | 千問只負責拆條件，不會亂講；但 PR #48 改成聊天後，4B 模型偶爾說錯數字或把不符合的課說成符合 | 卡片和價格由資料庫組成、程式核對；低於門檻就說「找不到」；微調模型學會「清單外的不講」 |
| **RAG** | 沒有。ADR 0007 只寫了規劃 | 正式功能：先檢索課程與平台說明，再交給模型回答，附上來源 |
| **Embedding** | 有，bge-m3，1024 維 | 沿用 bge-m3（中文比 e5-small 好、已部署），維度 1024 |
| **餘弦相似度** | 有排序，**沒有門檻**、沒有驗收報表 | 加門檻（在驗證集上校準，不直接沿用 0.83），出驗收報表與分數分布圖 |
| **Top-k** | 篩完全部排序，PR #48 取 6 門 | 依驗收結果決定（預計 3～6），寫進設定 |
| **Chunking** | 一門課一筆（標題＋曲風＋介紹，最多 1000 字） | 課程維持一門一筆（說明見 §2.2）；平台說明依標題切塊 |
| **多輪查詢改寫** | 原本靠規則累積條件；PR #48 合併最近 3 句學生的話 | 由微調後的模型輸出「獨立查詢句」，失敗時退回合併最近幾句 |
| **向量資料庫** | PostgreSQL 的 JSONB 欄位，在 Python 裡逐筆算 cosine | **pgvector**：`vector(1024)` 欄位 ＋ HNSW 索引，在資料庫裡用 `<=>` 排序 |

### 不做的事

- 不讓模型寫入或修改課程資料（ADR 0007）。
- 不用使用者的搜尋紀錄自動重新訓練。之後要做，另開 ADR 討論資料保存與同意。
- 不換掉 bge-m3、不換掉千問 4B 這個基礎模型（只加 adapter）。

---

## 1. 階段總覽

| 階段 | 內容 | 產出 | 依賴 |
|---|---|---|---|
| **P0** | 前置確認（技術驗證） | 三個 spike 的結論 | — |
| **P1** | pgvector 向量資料庫 | Migration、索引工具改寫、Docker／CI／雲端設定 | P0 |
| **P2** | RAG 檢索＋餘弦相似度驗收 | 檢索服務、評估資料集、驗收報表與圖 | P1 |
| **P3** | 聊天式找課（PR #48 已在 main） | `/api/course-chat` 接上 RAG、階段提示 | P2 |
| **P4** | 推薦問題（30 筆驗證過、隨機 3 筆） | 資料表、驗證腳本、API、前端按鈕 | P2、P3 |
| **P5** | QLoRA 微調 | 訓練資料、訓練／評估腳本、Loss 圖、過擬合分析 | P2（需要檢索結果當訓練輸入） |
| **P6** | 微調模型上線 | 轉成 Ollama 模型、閘道開放、A/B 比較 | P5 |
| **P7** | 文件、ADR、整合測試、PR | ADR 0012、說明文件、`verify_merge.py` 通過 | 全部 |

P3／P4 和 P5 可以平行做：P3、P4 先用原版千問跑通，P5 完成後在 P6 換上微調模型。

---

## 2. 各階段細節

### P0 前置確認（先做，結果會影響後面的設計）

| Spike | 要確認什麼 | 不成立時的退路 |
|---|---|---|
| **A. MLX adapter → Ollama** | MLX 訓練出的 LoRA 能不能變成 Ollama 模型：`mlx_lm.fuse --dequantize` → llama.cpp `convert_hf_to_gguf.py` → 量化 `Q4_K_M` → `ollama create melo-qwen3-4b-ft` | 用 Ollama 的 `ADAPTER` 指令直接載 safetensors adapter；再不行就在閘道旁跑 `mlx_lm.server` 提供微調模型 |
| **B. pgvector 映像** | `pgvector/pgvector:pg17` 能不能直接讀現有 `postgres17_data` volume；Supabase 是否已能 `create extension vector` | 本機 volume 不相容就先備份、重建再還原；Supabase 不支援就改在後端存陣列（不太可能） |

**驗收：** 兩個 spike 的結論寫進本文件 §5「P0 結論」。

### P1 pgvector 向量資料庫

**資料表（新 Migration，接在當時唯一的 Alembic head 後面）：**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- 取代 course_embeddings 的 JSONB 欄位
CREATE TABLE rag_documents (
  id            uuid PRIMARY KEY,
  source_type   text NOT NULL,          -- 'course' | 'platform_guide'
  source_id     text NOT NULL,          -- 課程 id 或說明文件的段落 id
  chunk_index   int  NOT NULL DEFAULT 0,
  content       text NOT NULL,          -- 拿去算向量的原文（課程只做排序，事實仍以 courses 為準）
  content_hash  char(64) NOT NULL,
  model_version char(64) NOT NULL,      -- bge-m3 digest
  embedding     vector(1024) NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_type, source_id, chunk_index, model_version)
);
CREATE INDEX ix_rag_documents_embedding
  ON rag_documents USING hnsw (embedding vector_cosine_ops);
```

- **向量要重算，不直接搬。** P0 發現課程介紹夾帶示範資料的固定文字，見 §5。改寫 `course_text()` 去掉這些文字後，426 門課全部重建索引。舊表 `course_embeddings` 保留一個版本後再刪。
- `scripts/index_course_embeddings.py` 改成寫入 `rag_documents`，**檔名不變**（快速啟動和雲端指令都用這個名字）：同樣有試跑、`--apply --confirm-database`、`pending=0` 檢查。
- 向量先做 L2 正規化再存，`1 - (embedding <=> q)` 就是餘弦相似度。

**要一起改的地方：**

| 檔案 | 改什麼 |
|---|---|
| `docker-compose.yml` | `postgres:17` → `pgvector/pgvector:0.8.1-pg17-trixie`（PostgreSQL 17.11、Debian 13，和現在的映像相同，見 P0） |
| `.github/workflows/database.yml` | 測試用資料庫的 image 同上 |
| `backend/requirements.txt` | 加 `pgvector`（SQLAlchemy 的 `Vector` 型別） |
| `scripts/ops/database_refs.py` | 登記新 migration，備份工具才認得 |
| Migration 本身 | `CREATE SCHEMA IF NOT EXISTS extensions; CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;`，本機和 Supabase 都把 vector 放在 `extensions` schema；欄位型別寫成 `extensions.vector(1024)`，不依賴 search_path |
| `scripts/ops/postgres.py`、`scripts/ops/restore.py` | 備份只 dump `public` schema，不含 `extensions` 裡的 vector 型別。還原容器改用 `pgvector/pgvector:0.8.1-pg17-trixie`，並在 `pg_restore` 前先建 `extensions` schema 和 vector extension，否則還原演練會失敗 |
| 雲端（Supabase） | Render 部署時 `deploy/start.sh` 會自動跑 `alembic upgrade head`；雲端連線用 `postgres` 角色，可以建 extension。部署前先手動備份，並用 `scripts.cloud_command migrate` 先跑過一次 |

**驗收：** 從空資料庫跑 migration 001→最新通過；搬移後 426 筆向量、`pending=0`；`EXPLAIN` 看得到用了 HNSW 索引。

### P2 RAG 檢索＋餘弦相似度驗收

**檢索流程（新 `backend/services/rag_retrieval.py`）：**

1. **查詢改寫**：多輪對話時，把「那便宜一點的呢？」改寫成獨立查詢句。P5 前先用規則（參考 health-news：問句短於 12 字或有「那、這些、它」等詞，就合併上一題）；P6 換成模型輸出。
2. **硬條件篩選**：程度、上課方式、地區、預算繼續用 SQL 篩（沿用 `_apply_required_filters`），向量不負責判斷這些條件。**要修正**：上課方式是空值的課（「線上／實體皆可」，135 門）目前會被排除，見開發紀錄 P1-9。
3. **向量檢索**：在篩完的已發布課程裡，用 `ORDER BY embedding <=> :q LIMIT k` 取前 k 門。
4. **門檻**：相似度低於門檻 `τ` 的課程不交給模型。全部低於門檻時直接回覆「目前找不到符合的課程」，並建議放寬條件。不讓模型硬湊答案。
5. **平台說明**：問「怎麼約課」這類問題時，從 `platform_guide` 取前 2 段。

**為什麼課程不切塊：** 一門課的介紹最長 1000 字，在 bge-m3 的長度上限內，一門一筆就能保留完整語意，卡片也能直接對應到一門課。缺點是介紹很長、主題很多的課，向量會被平均掉。等到有超過 1000 字的課程再改成切塊。

**驗收資料集（`evaluations/rag/`）：**

- 約 150 句查詢，每句標註「應該找到的課程 id」。來源：既有的 16 句、`shared_ai_smoke.json`、依 426 門課的 80 個主題撰寫的口語問句，加上約 20 句**不該有結果**的查詢（例如學吉他、寫數學作業）。
- 依主題分組切成 **dev 70% ／ test 30%**，同一主題的句子不跨組。
- 門檻 `τ` 和 `k` **只在 dev 上決定**，test 只在最後跑一次報數字。

**驗收指標與圖（`docs/ai-course-finder/retrieval/`）：**

| 指標 | 意思 | 目標（暫定，P2 依 dev 結果調整） |
|---|---|---|
| Recall@3 | 前 3 名有沒有包含應找到的課 | ≥ 0.85 |
| MRR | 正確的課平均排第幾 | ≥ 0.70 |
| 無結果查詢正確拒答率 | 不該有結果的查詢，全部低於門檻 | ≥ 0.90 |
| 檢索延遲 p95 | pgvector 查詢本身 | < 100 ms |

- `score_distribution.png`：相關與不相關的相似度分布，標出門檻 τ。
- `threshold_sweep.png`：門檻從 0.3 到 0.9，Recall 與拒答率的變化。
- `report.md`：數字、設定、模型版本、資料集雜湊，由腳本產生。

### P3 聊天式找課（PR #48 已合併進 main）

沿用 PR #48 已經做好、也有測試的部分：

- `POST /api/course-chat`：對話只存在瀏覽器，送最近 20 則。
- 系統提示詞的 8 條規則（只推薦清單內的課、資料沒寫就說沒寫、婉拒無關問題…）。
- 卡片由資料庫組成；超過預算、不在指定地區、回覆寫錯價格都在卡片上用紅字提醒。
- AI 沒回應時改列前 3 門課，不回錯誤。

這次要改的：

- 把 `_candidates` 改用 P2 的 `rag_retrieval`（pgvector、門檻、查詢改寫）。
- 回覆最後附「參考來源」：課程卡片＋用到的平台說明段落，由程式組成，不讓模型自己寫。
- 前端：聊天泡泡、輸入中動畫、清除對話、手機版排版。
- **不做串流**（決策 4）。改成依階段顯示「正在找課…」「正在整理回覆…」，降低等待感，也不影響回覆完成後的卡片核對。

### P4 推薦問題（30 筆驗證過、隨機 3 筆）

**資料表 `course_chat_starters`：**

| 欄位 | 說明 |
|---|---|
| `id` | |
| `text` | 按鈕上的文字，例如「我是成人零基礎，想學自彈自唱」 |
| `category` | `course_search`（找課）／`platform_howto`（平台怎麼用）／`criteria`（條件組合，例如台中、線上、預算） |
| `expected_course_ids` | 驗證時應該找到的課 |
| `verified_at`、`verified_model_version`、`top_score` | 最後一次驗證的時間、模型版本、最高相似度 |
| `is_active` | 驗證沒過就自動停用 |

- **30 筆的組成**：找課 18 筆、條件組合 7 筆、平台使用 5 筆。不和 P2 的 test 集重複，避免驗收被污染。
- **驗證腳本** `scripts/verify_chat_starters.py`：每筆都實際跑一次檢索，至少有 1 門課高於門檻、而且包含預期的課才算通過；沒過就設 `is_active=false`，報表列出原因。課程改了、重建索引後要重跑。
- **API**：`GET /api/course-chat/starters` 從 `is_active` 的資料裡隨機回傳 3 筆。
- **前端**：對話是空的時候顯示 3 個按鈕，點了就直接當成使用者的第一句送出；旁邊放「換一組」。

### P5 QLoRA 微調

**微調什麼任務：** 只微調**需求解析＋查詢改寫**（輸出 JSON），不微調聊天回覆（決策 2）。

| 任務 | 輸入 | 輸出 | 為什麼 |
|---|---|---|---|
| ① 需求解析＋查詢改寫（主要） | 對話前文＋本輪訊息 | `{"changes":[...], "rewritten_query":"...", "intent":"course_search｜platform_howto｜off_topic", "question":""}` | 答案明確，loss 之外還能算**準確率**；直接影響檢索品質和幻覺 |

**資料（`evaluations/qwen_lora/`，參考冷笑話專案）：**

- 用 426 門課的 80 個主題、地區、預算、程度組合**合成**多輪對話，加上人工撰寫的困難案例（否定、更正、「前者」、無關請求、提示詞注入）。
- 預計 600～900 筆前綴樣本。**依主題分組**切 train 70%／valid 15%／test 15%，同一段對話、同一主題的變化句不跨組。
- 用 Codex／Claude 產生的資料要人工抽查至少 10%，記錄在 `quality_review.md`。

**訓練設定（起點，P5 視結果調整）：**

| 設定 | 值 | 依據 |
|---|---|---|
| 基礎模型 | `mlx-community/Qwen3-4B-Instruct-2507-4bit`（本機已下載） | 和 Ollama 線上用的是同一個模型 |
| 方法 | 4-bit 量化權重凍結＋LoRA（＝QLoRA） | |
| LoRA rank／scale／dropout | 8／16／0.05 | 冷笑話專案 |
| 套用層 | 最後 16 層的 `q_proj`、`v_proj` | 冷笑話專案 |
| learning rate | 1e-4（11/3 的 run-01、02 也是這個） | |
| iters | 400，每 40 步跑一次 valid | |
| loss | 只算助手回答的交叉熵，遮罩 prompt 和 padding | 冷笑話專案的 `answer_loss` |
| 選權重 | 只看 valid loss；test 完全不參與 | |
| seed | 42 | |

**腳本（照冷笑話專案的編號方式，放在 `scripts/qlora/`）：**

```
00_download_model.py   01_build_dataset.py   02_inspect_data.py
03_train.py            04_evaluate.py        05_plot.py
06_export_ollama.py    07_report.py
```

**Loss 圖與過擬合分析（`docs/ai-course-finder/training/`）：**

> 註：冷笑話專案的 Loss 只有 `report.md` 裡的表格，沒有圖片。這次另外用 matplotlib 畫成 PNG。

| 圖 | 內容 |
|---|---|
| `loss_curves.png` | train loss（每 10 步）、valid loss（每 40 步）、標出最佳 step；test loss 用水平虛線標出最佳 adapter 的值 |
| `overfitting_gap.png` | valid − train 的差距隨步數變化 |
| `base_vs_adapter.png` | 原始模型和最佳 adapter 在 valid／test 的 loss、perplexity 長條圖 |
| `task_accuracy.png` | test 集的 JSON 格式正確率、各欄位正確率、意圖分類正確率，原始模型與微調模型對照 |

**判斷過擬合的規則（寫在報告裡）：** train loss 持續下降、valid loss 連續 2 次評估回升，就判定為過擬合，並採用 valid 最低的那一步。報告要寫出最佳 step、之後 valid 上升了多少，以及 test loss 是否和 valid 一致。如果 test 明顯比 valid 差，代表切分或資料有問題，要回頭檢查。

**驗收：** test 集 JSON 格式正確率 ≥ 98%、欄位正確率比原始模型高、test loss 低於原始模型；報告列出至少 20 句原始模型和微調模型的輸出原文。

### P6 微調模型上線

- 用 P0 spike A 確認的方式轉成 Ollama 模型 `melo-qwen3-4b-ft`：`mlx_lm fuse --dequantize` → `ollama create -q int4`。
- **轉檔後重跑 P5 的 test 準確率**：訓練用 MLX 4-bit，上線是 Ollama `int4`，兩者量化方式不同，要確認轉完沒有變差。
- 閘道的 `AI_GATEWAY_CHAT_MODELS` 加上新模型；後端新設定 `COURSE_PLANNER_LLM_MODEL`，預設仍是原版千問，設了才用微調版，可以隨時切回。
- 用 P2 的 test 集跑端到端比較（原版 vs 微調版）：Recall@3、拒答率、延遲。

### P7 文件、測試、PR

- **ADR 0012**：AI 找課改用 pgvector RAG＋微調模型，記錄門檻、k 值、為什麼課程不切塊。
- 更新 ADR 0007（放寬「RAG 只用知識文件」：課程內容也可以檢索，但事實仍以 `courses` 為準）、[AI功能啟動說明.md](../../AI功能啟動說明.md)、[快速啟動.md](../../快速啟動.md)（換 pgvector image、重建索引、驗證推薦問題）。
- 測試：pgvector migration、檢索門檻、拒答、查詢改寫、推薦問題 API、卡片核對，加上 PR #48 原有的 9 個測試。
- `python scripts/verify_merge.py` 全部通過後開 PR。

---

## 3. 預計新增或修改的檔案

```text
backend/alembic/versions/0xx_pgvector_rag.py          新：extension、rag_documents、搬移資料
backend/alembic/versions/0xx_course_chat_starters.py  新
backend/models/rag_document.py、course_chat_starter.py 新
backend/services/rag_retrieval.py                     新：查詢改寫、篩選、pgvector 檢索、門檻
backend/services/course_chat.py、routers/course_chat.py  來自 PR #48，改接 rag_retrieval
backend/services/ai_semantic.py                       保留 cosine() 給驗收用，排序移到資料庫
scripts/index_rag_documents.py                        取代 index_course_embeddings.py
scripts/verify_chat_starters.py                       新
scripts/qlora/00～07_*.py                             新
evaluations/rag/、evaluations/qwen_lora/               評估與訓練資料（不含個資）
docs/ai-course-finder/retrieval/、training/            報表與圖
frontend/src/components/common/AiAssistButton.vue     聊天介面、推薦問題按鈕
docker-compose.yml、.github/workflows/database.yml    pgvector image
```

模型權重、adapter、GGUF 檔不進 Git（放 `.scratch/qwen-lora/`），只提交設定、指標與圖。

---

## 4. 已確認的決策（2026-11-09）

| # | 問題 | 決定 |
|---|---|---|
| 1 | PR #48 | 已合併進 `main`，本分支從 b94fc26 開出 |
| 2 | 微調範圍 | 只做需求解析＋查詢改寫 |
| 3 | 雲端 | Render＋Supabase 一起換成 pgvector，含備份與還原工具 |
| 4 | 串流回覆 | 不做，改用階段提示 |
| 5 | 推薦問題 30 筆 | 由 Claude 依課程主題草擬，Ollie 審過再進資料庫 |

## 5. P0 結論（2026-11-09）

### Spike A：MLX adapter → Ollama　✅ 通過

- 路線：`mlx_lm fuse --dequantize`（7.5 GB）→ `ollama create -q int4`（3.4 GB），沿用線上千問的 Modelfile 模板。
- 這版 Ollama（0.40.15）從 safetensors 匯入時只支援 `int4`、`int8`、`nvfp4`、`mxfp4`、`mxfp8`，**不支援 `Q4_K_M`**，所以不需要 llama.cpp，改用 `int4`。
- 用需求解析提示詞實測：輸出合法 JSON、沒有思考內容，速度和原版相同（約 3.4 秒）。
- 測試用的是 11/3 留下的 adapter，只驗證轉檔流程，不代表模型品質。

### Spike B：pgvector　✅ 通過

- `pgvector/pgvector:pg17` 是 Debian 12，現在的 `postgres:17` 是 Debian 13，系統函式庫不同，可能造成排序規則（collation）版本不一致。改用 **`pgvector/pgvector:0.8.1-pg17-trixie`**：PostgreSQL 17.11、glibc 2.41，和現在完全相同。
- 用現有 volume 的**複本**啟動：426 門課都在，日誌沒有警告；建 `extensions.vector`、HNSW 索引、`<=>` 排序都正常。
- Supabase（唯讀查詢）：PostgreSQL 17.11，pgvector **0.8.2 可用但還沒安裝**，`extensions` schema 已存在，`search_path` 包含 `extensions`；資料庫 20 MB。
- 雲端 Alembic 目前在 **022**，PR #48 的 023 還沒部署。部署本分支時會一次跑 023 和新的 migration。

### 額外發現：影響 RAG 品質

1. **課程介紹夾帶固定文字。** 示範課程的 `description` 都有「[虛構測試資料・AICourseFinder]」「原示範工作室…」「原型有效期限…」，這些也被算進向量，讓所有課程看起來都很像。
2. **相似度分布被壓縮。** 426 門課兩兩之間的相似度最低 0.61、平均 0.76、中位數 0.75。所以 0.83 這種固定門檻在這裡沒有意義，必須在驗證集上校準。
3. **同名課程很多。** 例如「婚禮歌曲伴奏・慢速探索主題練習」有 3 門（不同老師），彼此相似度 0.999。驗收時「應該找到的課」要允許多個 id，Recall 以「找到其中任一門」計算。

→ P1 改寫 `course_text()` 去掉第 1 點的固定文字後重建全部向量；P2 再比較去除前後的分數分布。
