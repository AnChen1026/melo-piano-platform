# AI 功能啟動說明

> 只想照步驟啟動、不想看說明：看 **[快速啟動.md](快速啟動.md)**。

讓這三個功能在你的電腦上跑起來：

| # | 功能 | 在網站哪裡 |
|---|---|---|
| ① | **AI 出題** | 老師 → 作業 → 新增 → 題庫作業上傳 |
| ② | **音訊評分＋練習回饋** | 學生上傳錄音後，系統比對音高、節奏，寫一段文字回饋 |
| ③ | **AI 找課** | 首頁右下角「AI 找課」 |

> **這份文件只講「在自己電腦上跑」，雲端共用環境照舊**
> - 這裡的步驟是給組員在自己電腦開發、測試用的：資料庫是 Docker 裡的 PostgreSQL，AI 走本機閘道（`host.docker.internal`）。
> - 共用測試站（Render）、Supabase 資料庫與 Storage、接 Ollie Mac 上模型的 ngrok 通道都**沒有移除，也沒有改動**，用法照舊看 [deployment.md](deployment.md) 和 [ai-startup-checklist.md](ai-startup-checklist.md)。
> - 雲端要部署新版本前，記得先跑 `python -m scripts.cloud_command --config .env.cloud.json migrate`，因為這版多了 AI 出題背景工作的資料表（`022_quiz_generation_jobs`）。

> **怎麼看這份文件**
> - 一次只做一步，做完把 `[ ]` 想成打勾。
> - 每步最後有「✅ 看到這個就對了」。**沒看到就不要往下**，去最後的〈出問題時〉查。
> - 灰底框框裡的指令可以整段複製貼上。Windows 和 Mac 指令不一樣，**只做你那一台的**。
> - `.env` 裡的金鑰、密碼不要傳到群組，也不要 commit。

---

## 第 0 步：先選路線（1 分鐘）

回答一個問題：**你要用哪一種 AI？**

| 你有的東西 | 走哪條路 | 能用的功能 | 花錢嗎 |
|---|---|---|---|
| OpenAI API 金鑰 | **路線 A** | ① 出題、② 回饋、③ AI 找課（聊天，不比對意思） | 用多少付多少 |
| 電腦可以裝 Ollama（記憶體 8GB 以上） | **路線 B** | ① 出題、② 回饋、③ AI 找課 | 免費 |

- **AI 找課（③）兩條都能聊天**；但「比對意思找最相近的課」要路線 B 的 bge-m3，路線 A 只會依條件篩選、照新到舊挑課。
- **音訊評分本身**（比對音高、節奏）不需要任何 AI，做完第 1 步就能用；A 或 B 只影響評分後那段「文字回饋」寫得好不好。
- 兩條都想要也可以：先做 A，之後再做 B。

👉 選好了就往下做 **第 1 步**（大家都要做）。

---

## 第 1 步：把網站跑起來（大家都要做，約 15 分鐘，第一次要下載比較久）

### 1-1 裝 Docker Desktop
- [ ] 到 <https://www.docker.com/products/docker-desktop/> 下載安裝。
- [ ] 打開 Docker Desktop，等左下角變成綠色 **Engine running**。

✅ 看到 Docker Desktop 顯示 **Engine running** 就對了。

### 1-2 拿到最新程式
在專案資料夾（`AIPE04_group3`）打開終端機：

```bash
git pull origin main
```

✅ 看到 `Already up to date.` 或一串更新的檔案名稱就對了。

### 1-3 準備 `.env`（只有第一次要做）
`.env` 是放設定和金鑰的檔案。如果專案資料夾裡**已經有 `.env`，跳過這步**。

Windows（PowerShell）：
```powershell
Copy-Item .env.example .env
```

Mac：
```bash
cp .env.example .env
```

✅ 專案資料夾裡出現 `.env` 檔就對了。

### 1-4 啟動（第一次會重新打包，要等幾分鐘）
```bash
docker compose up --build -d
```

等它跑完，再輸入：
```bash
docker compose ps
```

✅ 看到三行：`python-dev-box`、`vue-dev-box`、`aipe04-postgres`，而且後端那行有 **(healthy)** 就對了。
（剛啟動的前 40 秒可能是 `starting`，等一下再打一次 `docker compose ps`。）

### 1-5 打開網站
瀏覽器打開 <http://localhost>

✅ 看到 melo. 首頁就對了。**② 音訊評分這時已經能用**（回饋文字會比較簡短，做完 A 或 B 才會由 AI 寫）。

👉 接下來：走 **路線 A** 就做第 2 步；走 **路線 B** 就跳到第 3 步。

---

## 第 2 步：路線 A — 用 OpenAI（約 5 分鐘）

### 2-1 拿金鑰
- [ ] 到 <https://platform.openai.com/api-keys> 登入，按 **Create new secret key**。
- [ ] 複製那串 `sk-` 開頭的字（只會顯示一次）。
- [ ] 這個帳號要有儲值，否則會出現 429 錯誤。

✅ 手上有一串 `sk-...` 就對了。

### 2-2 改 `.env`
用記事本或 VS Code 打開專案資料夾裡的 `.env`，**找到這幾行改成下面這樣**（沒有那一行就自己加在最後）：

```env
OPENAI_API_KEY=sk-貼上你的金鑰
LLM_PROVIDER=openai
PRACTICE_FEEDBACK_LLM_PROVIDER=openai
QUIZ_GENERATION_LLM_PROVIDER=openai
```

- `LLM_PROVIDER` 管課前摘要。
- `PRACTICE_FEEDBACK_LLM_PROVIDER` 管 ② 練習回饋。
- `QUIZ_GENERATION_LLM_PROVIDER` 管 ① AI 出題。

存檔。

### 2-3 讓後端讀新設定
```bash
docker compose up -d --force-recreate backend
```

✅ 再打 `docker compose ps`，後端回到 **(healthy)** 就對了。

### 2-4 確認有用
```bash
docker exec python-dev-box python -c "from backend.services import llm; print(llm.generate_text_with_reason('用一句話回答', '四分音符幾拍？', feature=llm.FEATURE_QUIZ_GENERATION))"
```

✅ 看到 `('四分音符...一拍...', None)` 這種**後面是 None** 的結果就對了。
❌ 後面是一段文字（例如 `沒有設定 OPENAI_API_KEY`）→ 回到 2-2 檢查。

🎉 路線 A 完成：① 出題、② 回饋都用 OpenAI 了。

---

## 第 3 步：路線 B — 用 Ollama 本機模型（約 30 分鐘，大部分是在等下載）

> 這條路要開著 **3 樣東西**：Docker、Ollama、閘道（一個終端機視窗）。閘道是一道門：只讓我們的後端、用正確的金鑰、用指定的模型來問 Ollama。

### 3-1 裝 Ollama
- [ ] 到 <https://ollama.com/download> 下載**桌面 App** 安裝，打開它。Mac 右上角、Windows 右下角會出現羊駝圖示。
- 以前用 Homebrew（`brew install ollama`）裝過的，那是沒有畫面的命令列版。要改用 App 的話，先停掉舊的，不然兩個會搶同一個埠：`brew services stop ollama`（如果是在某個終端機視窗開的 `ollama serve`，就在那個視窗按 Ctrl-C）。

✅ 看得到羊駝圖示，而且終端機打 `ollama list` 沒有出錯（可能是空的）就對了。
❌ 出現 `could not connect to ollama server` → Ollama 有裝但沒開，把 App 打開再試。

### 3-2 下載模型（約 6.5GB，要等）
```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama pull bge-m3:567m
ollama pull hf.co/Ollie12304/melo-qwen3-4b-ft
ollama cp hf.co/Ollie12304/melo-qwen3-4b-ft melo-qwen3-4b-ft
```

- 第一個是千問（出題、回饋、AI 找課的聊天回覆都用它）。
- 第二個只給 ③ AI 找課用（把課程內容轉成可以比對的數字）。
- 第三個是我們用 QLoRA 微調過的千問 4B，只給 ③ AI 找課「整理學生需求」用。它放在 [Hugging Face](https://huggingface.co/Ollie12304/melo-qwen3-4b-ft)，Windows、Mac 都能跑。最後一行把它改成網站認得的名字。沒下載也沒關係，網站會改用規則整理需求，只是比較看不懂「一千二」「下班後」這類說法。

✅ 再打 `ollama list`，看得到 `qwen3:4b-instruct-2507-q4_K_M`、`bge-m3:567m`、`melo-qwen3-4b-ft` 就對了。**名字要一模一樣**，網站只認這幾個。（清單裡還會有一個 `hf.co/…` 開頭的，是同一個模型，不會多占空間。）

### 3-3 讓 Ollama 讀得下長一點的教材
- [ ] 點羊駝圖示 → **Settings**，把 **Context length** 調到 **16k**。

✅ Settings 裡 Context length 顯示 16k 就對了。

Settings 裡找不到這個選項（舊版 App）就改用指令：

Windows（PowerShell）：
```powershell
setx OLLAMA_CONTEXT_LENGTH 16384
```

Mac：
```bash
launchctl setenv OLLAMA_CONTEXT_LENGTH 16384
```

然後**把 Ollama 完全關掉再打開**（羊駝圖示 → Quit，再重新打開）。

用命令列版、沒有 App 的人，以後都用這行開 Ollama（視窗開著別關）：
```bash
OLLAMA_CONTEXT_LENGTH=16384 ollama serve
```

### 3-4 做一把閘道金鑰，放進 `.env`
```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

（沒有 `uv` 的話先裝：<https://docs.astral.sh/uv/getting-started/installation/>）

複製印出來的那串字，打開 `.env`，**找到或加上這幾行**：

```env
AI_COURSE_GATEWAY_URL=http://host.docker.internal:18763
AI_COURSE_GATEWAY_TOKEN=貼上剛剛那串字
LLM_PROVIDER=local
PRACTICE_FEEDBACK_LLM_PROVIDER=local
QUIZ_GENERATION_LLM_PROVIDER=local
COURSE_PARSER_LLM_MODEL=melo-qwen3-4b-ft
```

- `host.docker.internal` 是 Docker 裡「這台電腦」的意思，**照抄不要改**。
- 三行 `PROVIDER` 都要寫 `local`：只寫 `LLM_PROVIDER` 的話，出題和回饋不會跟著換。
- `COURSE_PARSER_LLM_MODEL` 讓 ③ AI 找課用微調模型整理需求。3-2 沒下載第三個模型的話，這行留空。

存檔。

✅ `.env` 裡有這 6 行，而且金鑰那行不是空的就對了。

### 3-5 開閘道（開一個新的終端機視窗，**之後都不要關**）
在專案資料夾打開**新的**終端機：

Windows（PowerShell）：
```powershell
$env:AI_GATEWAY_TOKEN = (Select-String -Path .env -Pattern '^AI_COURSE_GATEWAY_TOKEN=(.*)').Matches[0].Groups[1].Value
$env:AI_GATEWAY_TIMEOUT_SECONDS = "180"
$env:AI_GATEWAY_CHAT_MODELS = "qwen3:4b-instruct-2507-q4_K_M,melo-qwen3-4b-ft"
uv run uvicorn scripts.local_ai_gateway:app --host 127.0.0.1 --port 18763 --no-access-log
```

Mac：
```bash
export AI_GATEWAY_TOKEN="$(grep '^AI_COURSE_GATEWAY_TOKEN=' .env | cut -d= -f2-)"
export AI_GATEWAY_TIMEOUT_SECONDS=180
export AI_GATEWAY_CHAT_MODELS="qwen3:4b-instruct-2507-q4_K_M,melo-qwen3-4b-ft"
uv run uvicorn scripts.local_ai_gateway:app --host 127.0.0.1 --port 18763 --no-access-log
```

`AI_GATEWAY_CHAT_MODELS` 是閘道允許使用的模型清單。沒列在裡面的模型，閘道會拒絕。

✅ 最後一行出現 `Uvicorn running on http://127.0.0.1:18763` 就對了。**這個視窗開著別關**（關掉 = AI 停掉）。

### 3-6 讓後端讀新設定
回到**原本的**終端機：
```bash
docker compose up -d --force-recreate backend
```

✅ `docker compose ps` 後端回到 **(healthy)** 就對了。

### 3-7 確認 ① 出題、② 回饋走本機
```bash
docker exec python-dev-box python -c "from backend.services import llm; f=llm.FEATURE_QUIZ_GENERATION; print(llm.provider_for(f), llm.generate_text_with_reason('用一句話回答', '四分音符幾拍？', feature=f))"
```

✅ 看到開頭是 **`local`**，後面是 `('...一拍...', None)` 就對了。第一次要載入模型，可能等 10～30 秒。
❌ 開頭是 `openai` → 3-4 的三行 `PROVIDER` 沒改到，或 3-6 沒做。
❌ 出現 `503` → 3-5 的閘道視窗沒開，或 Ollama 沒開。

🎉 到這裡 ① 出題、② 回饋都用本機千問了。要 ③ AI 找課再做下面三步。

### 3-8 ③ AI 找課：記下模型版本
AI 找課要知道 `bge-m3:567m` 的版本號（一串 64 個字的英數字）。

Windows（PowerShell）：
```powershell
(Invoke-RestMethod http://127.0.0.1:11434/api/tags).models | Where-Object name -eq 'bge-m3:567m' | Select-Object -ExpandProperty digest
```

Mac：
```bash
curl -s http://127.0.0.1:11434/api/tags | python3 -c 'import json,sys; print(next(m["digest"] for m in json.load(sys.stdin)["models"] if m["name"] == "bge-m3:567m"))'
```

複製印出來那串，`.env` 加一行：
```env
AI_COURSE_EMBEDDING_VERSION=貼上那串
```

再讓後端讀一次設定：
```bash
docker compose up -d --force-recreate backend
```

✅ `.env` 有這行、後端回到 healthy 就對了。

### 3-9 ③ AI 找課：把課程建立索引（課程有改就要重做）
在**原本的**終端機（不是閘道那個）。先「試跑」，不會寫入任何東西：

Windows（PowerShell）：
```powershell
$env:AI_COURSE_GATEWAY_URL = "http://127.0.0.1:18763"
$env:AI_COURSE_GATEWAY_TOKEN = (Select-String -Path .env -Pattern '^AI_COURSE_GATEWAY_TOKEN=(.*)').Matches[0].Groups[1].Value
$env:AI_COURSE_EMBEDDING_VERSION = (Select-String -Path .env -Pattern '^AI_COURSE_EMBEDDING_VERSION=(.*)').Matches[0].Groups[1].Value
uv run python -m scripts.index_course_embeddings
```

Mac：
```bash
export AI_COURSE_GATEWAY_URL=http://127.0.0.1:18763
export AI_COURSE_GATEWAY_TOKEN="$(grep '^AI_COURSE_GATEWAY_TOKEN=' .env | cut -d= -f2-)"
export AI_COURSE_EMBEDDING_VERSION="$(grep '^AI_COURSE_EMBEDDING_VERSION=' .env | cut -d= -f2-)"
uv run python -m scripts.index_course_embeddings
```

✅ 印出有幾門課、幾門要建索引就對了。

確認數字合理後，**同一個視窗**真的寫入：
```bash
uv run python -m scripts.index_course_embeddings --apply --confirm-database aipe04
```

✅ 跑完沒有紅色錯誤，最後一行是 `indexed=` 和 `published=` 一樣的數字就對了。想再確認一次，可以重跑上面的試跑指令，看到 `pending=0` 代表全部建好。

向量存在資料庫的 pgvector（`rag_documents` 表）。第一次 pull 到這個版本時，`docker compose up --build -d` 會把資料庫換成內建 pgvector 的映像，資料不會消失。

### 3-9b ③ AI 找課：放入推薦問題
同一個視窗（剛剛的 `export` 還在）：
```bash
uv run python -m scripts.chat_starters --apply --confirm-database aipe04
```

✅ 最後一行 `passed=29/30 mode=apply` 就對了。每一題都用網站的檢索實際跑過，沒找到課的會自動停用。課程或索引改過要重跑。

### 3-10 ③ AI 找課：試用
- [ ] 打開 <http://localhost>，按右下角 **AI 找課**，打「我完全沒學過，想自彈自唱流行歌」。

✅ 10～30 秒內有一段回覆，下面附上提到的課程卡片就對了。可以接著問「台中有便宜一點的嗎？」或「怎麼約課？」。

想確認微調模型有在用（Windows、Mac 都一樣）：

```bash
docker exec python-dev-box python -c "from backend.services.ai_course_parser import parse_conversation as p; print(p([{'role': 'user', 'content': '預算一千二，平日下班後想學爵士'}]))"
```

✅ 看到 `'max_price': 1200, 'time_slot': '平日晚上', 'search_query': '爵士'` 就對了。
❌ 印出 `None` 代表沒用到微調模型，網站會改用規則解析。依序檢查 3-2、3-4、3-5，改完記得 `docker compose up -d --force-recreate backend`。

（直接 `ollama run melo-qwen3-4b-ft` 聊天不會得到 JSON，因為它要搭配網站的系統提示詞才會照格式回答。）

🎉 路線 B 完成：①②③ 都在你的電腦上跑。

---

## 之後每次開機要做的事（日常版）

**路線 A**
- [ ] 打開 Docker Desktop
- [ ] `docker compose up -d`

**路線 B**（多兩步）
- [ ] 打開 Docker Desktop
- [ ] 確認 Ollama 有開（看得到羊駝圖示）。App 裝好後預設開機就會自己啟動；Mac 可以到「系統設定 → 一般 → 登入項目」確認 Ollama 在清單裡
- [ ] `docker compose up -d`
- [ ] 開一個新終端機，做 **3-5** 開閘道（視窗不要關）

**有人 `git pull` 到新東西之後**，改成 `docker compose up --build -d`（多了新套件要重新打包）。

---

## 出問題時

| 看到什麼 | 原因 | 怎麼辦 |
|---|---|---|
| `docker compose ps` 後端一直不是 healthy | 後端起不來 | `docker compose logs backend --tail 50` 看最後幾行紅字 |
| AI 出題一直「排隊中／出題中」很久 | 本機模型慢，或閘道視窗被關了 | 確認閘道視窗還開著；本機模型出 10 題可能要好幾分鐘，可以先去做別的，出好會通知 |
| 測試或出題出現 `503 本機模型忙碌中或沒有開` | Ollama 沒開（常見：電腦重開、命令列版的視窗被關），或閘道沒開 | 先打 `ollama list`：出現 `could not connect` 就把 Ollama 打開；再確認閘道視窗還開著 |
| 出題失敗：「AI 服務現在比較忙」 | 模型同時被別的功能用，或雲端太忙 | 等一兩分鐘，在出題紀錄按「刪除」再重新送出 |
| 出題失敗：「沒有設定 OPENAI_API_KEY」 | 路線 A 金鑰沒填 | 回到 2-2 |
| 出題失敗：「沒有設定 AI_COURSE_GATEWAY_TOKEN」或「網址不是 https」 | 路線 B 的 `.env` 沒填好 | 回到 3-4，網址照抄 `http://host.docker.internal:18763` |
| 出題失敗：「422 …模型可能沒有開放」 | 用了閘道沒開放的模型 | 見下方〈想換更好的模型〉 |
| 用 PDF 出題失敗，TXT 可以 | Docker 還是舊版 | `docker compose up --build -d` |
| 用 PDF 出題失敗：「讀不到文字」 | PDF 是掃描的圖片 | 改用可以選取文字的 PDF，或存成 TXT |
| 錄音一直「分析中」 | 後端在算或出錯 | 等 1 分鐘；還是不行看 `docker compose logs backend --tail 50` |
| 練習回饋文字很短、像制式句子 | 沒有連到 AI，改用備用說明 | 路線 A 看 2-4、路線 B 看 3-7 |
| AI 找課沒有反應或照一般搜尋 | 閘道、模型名稱、版本號或索引有一項沒好 | 依序檢查 3-2（名字一模一樣）、3-5、3-8、3-9 |
| AI 找課聊天視窗沒有推薦問題 | 還沒放入推薦問題 | 做 3-9b |
| AI 找課能用，但看不懂「一千二」「下班後」 | 沒用到微調模型，網站自動改用規則 | 檢查 3-2 有 `melo-qwen3-4b-ft`、3-4 有 `COURSE_PARSER_LLM_MODEL`、3-5 有 `AI_GATEWAY_CHAT_MODELS` |
| `ollama pull hf.co/…` 失敗 | 網路連不到 Hugging Face | 換個網路再試；真的不行就先把 `COURSE_PARSER_LLM_MODEL` 留空 |
| 電腦變很慢、AI 回覆等很久 | 三個模型輪流載入，記憶體不夠（8GB 會吃緊） | 先把 `COURSE_PARSER_LLM_MODEL` 清空，少載入一個模型 |
| 改了 `.env` 好像沒用 | 後端還在用舊設定 | `docker compose up -d --force-recreate backend` |

---

## 想換更好的模型（選做）

千問 4B 出的題目偶爾會錯（所以老師一定要審查）。電腦記憶體夠的話可以換大一點的模型：

| 模型 | 建議記憶體 |
|---|---|
| `qwen3:4b-instruct-2507-q4_K_M`（預設） | 8GB |
| `qwen3:14b` | 約 16GB 以上 |
| `qwen3:30b-a3b-instruct-2507` | 約 32GB 以上 |

（記憶體是粗估，裝起來實際跑一次最準。）

1. 下載：`ollama pull qwen3:14b`
2. 閘道開放這個模型：在 **3-5** 的指令，`uv run` 那行前面多加一行
   - Windows：`$env:AI_GATEWAY_CHAT_MODELS = "qwen3:4b-instruct-2507-q4_K_M,qwen3:14b"`
   - Mac：`export AI_GATEWAY_CHAT_MODELS="qwen3:4b-instruct-2507-q4_K_M,qwen3:14b"`
   （一定要保留第一個，AI 找課要用。）
3. `.env` 指定哪個功能用新模型，然後 `docker compose up -d --force-recreate backend`：
   ```env
   QUIZ_GENERATION_LLM_MODEL=qwen3:14b
   PRACTICE_FEEDBACK_LLM_MODEL=qwen3:14b
   COURSE_CHAT_LLM_MODEL=qwen3:14b
   ```
   `COURSE_CHAT_LLM_MODEL` 管 ③ AI 找課的聊天回覆。實測 24GB 的 Mac mini：4B 一輪約 5～13 秒，14B 約 13～31 秒；14B 比較會照條件挑課、不會把成人課推給小朋友，約課流程也講得比較對。

---

## 微調模型：更新、停用、發現問題怎麼修

③ AI 找課的「整理學生需求」用的是 QLoRA 微調過的千問 4B（`melo-qwen3-4b-ft`）。比起規則，它比較看得懂「一千二」「下班後」這類說法，也會分辨學生是在找課、問平台怎麼用，還是聊無關的事。訓練過程與成果見 [開發紀錄](ai-course-finder/開發紀錄.md)。安裝已經包含在 3-2、3-4、3-5。

**模型出新版時（大家）**：重跑 3-2 的最後兩行。`ollama pull` 會下載新版，`ollama cp` 會蓋掉舊的 `melo-qwen3-4b-ft`。網站設定不用改。

**暫時不想用**：把 `.env` 的 `COURSE_PARSER_LLM_MODEL` 清空，然後 `docker compose up -d --force-recreate backend`。網站會改回規則解析，其他功能不受影響。

**發現 AI 找課有問題時**，先判斷是不是微調模型造成的：

| 現象 | 問題在哪 | 怎麼修 |
|---|---|---|
| 推薦的課不相關、排序怪 | 檢索、排序（`backend/services/rag_retrieval.py`） | 改程式，一般 PR |
| 回覆亂講、價格說錯 | 聊天回覆，用的是官方千問，不是微調模型 | 改 `backend/services/course_chat.py` 的提示詞，或換 14B（見上一節） |
| 預算、時段、上課方式等條件抓錯，或把找課當成無關問題 | 微調模型的需求解析 | 看下面 |

想確認問題是不是出在微調模型，可以先清空 `COURSE_PARSER_LLM_MODEL`，改回規則解析再測一次。如果問題還在，就跟微調模型無關。

**確定是微調模型的問題時：**

1. **大家都能做**：把出錯的句子和正確答案加進 `evaluations/qwen_lora/handwritten_test.jsonl`。如果是某一類說法沒學到，在 `scripts/qlora/build_dataset.py` 補上對應的片段，再送 PR。
2. **負責訓練的人做**（需要 Apple Silicon Mac）：照開發紀錄 P5 重新訓練，約 1～2 小時。用 `scripts/qlora/evaluate.py` 和舊版比較，確認新的句子學會了，原本會的也沒有退步。
3. **轉成 GGUF 並發布**：步驟寫在 `scripts/qlora/export_gguf.py` 的檔案開頭。腳本會做好本機模型和上傳資料夾，用 `scripts/qlora/evaluate_ollama.py` 驗收後再上傳 Hugging Face。上傳後，在群組通知大家重跑 3-2 的最後兩行。

如果修正內容改了需求解析的輸出格式（`backend/course_parser_spec.py`），一定要重新訓練。新模型和後端程式要同一天發布，不然舊模型輸出的格式，新後端會不認得，網站會自動改回規則解析。

---

## 補充：這些設定在做什麼（看不懂可以跳過）

- 後端呼叫 AI 都經過 `backend/services/llm.py`：看 `<功能>_LLM_PROVIDER` 決定用 `openai`、`gemini` 或 `local`（本機閘道）。AI 出題沒設定時預設用 OpenAI；課前摘要跟著 `LLM_PROVIDER`。
- 本機模型一次能讀、能寫的字數有限，所以 AI 出題會分批，每批 4 題。出題在背景跑，完成後老師在作業選單看到通知，審查時可以改答案。
- AI 找課用的是同一個閘道，細節在 [shared-local-ai.md](shared-local-ai.md)。現在是聊天顧問：先檢索最相關的課程，再讓模型只根據這些課程回答，回覆走 `COURSE_CHAT_LLM_PROVIDER`（沒設就跟 `LLM_PROVIDER`）。設計見 [ADR 0011](adr/0011-ai-course-chat.md)、[ADR 0012](adr/0012-pgvector-rag-and-fine-tuned-parser.md)，流程說明在 [AI找課聊天說明](AI找課聊天說明.md)。
