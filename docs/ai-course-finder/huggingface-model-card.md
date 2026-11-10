---
license: apache-2.0
base_model: Qwen/Qwen3-4B-Instruct-2507
language:
  - zh
tags:
  - gguf
  - ollama
  - lora
  - qlora
  - qwen3
---

# melo-qwen3-4b-ft

這是鋼琴教學平台 [melo.](https://github.com/AnChen1026/melo-piano-platform) 的「AI 找課」需求解析模型，以 Qwen3-4B-Instruct-2507 為基礎，用 QLoRA 微調而成。模型讀學生最近幾句對話，輸出一個 JSON，內容包含意圖、找課條件和檢索主題。

這是 iSpan AIPE04 第三組的課程專題，只供學習與研究。

## 使用方式

```bash
ollama pull hf.co/Ollie12304/melo-qwen3-4b-ft
ollama cp hf.co/Ollie12304/melo-qwen3-4b-ft melo-qwen3-4b-ft
```

模型要搭配專案裡的系統提示詞，才能輸出固定格式。提示詞在 [`backend/course_parser_spec.py`](https://github.com/AnChen1026/melo-piano-platform/blob/main/backend/course_parser_spec.py)，網站端的設定方式寫在專案的 `docs/AI功能啟動說明.md`。呼叫時請用 `temperature 0`，而且**不要**加 `response_format: json_object`。JSON 模式的限制解碼會讓模型偏離訓練時學到的格式，原因寫在專案的開發紀錄 P6-2。

輸入：

```text
學生：想準備兒童鋼琴檢定
```

輸出：

```json
{"intent": "course_search", "level": null, "delivery_mode": null, "region": null, "max_price": null, "time_slot": null, "search_query": "兒童鋼琴檢定"}
```

| 欄位 | 值 |
| --- | --- |
| `intent` | `course_search`（找課）、`platform_howto`（問平台怎麼用）、`off_topic`（無關） |
| `level` | 入門、初階、中階、進階 |
| `delivery_mode` | `online`、`in_person` |
| `region`、`max_price`、`time_slot` | 地區、每堂預算上限、時段 |
| `search_query` | 拿去做向量檢索的主題，沒有主題時是空字串 |

## 訓練

| 項目 | 設定 |
| --- | --- |
| 基礎模型 | `mlx-community/Qwen3-4B-Instruct-2507-4bit`（MLX） |
| 方法 | LoRA，rank 8、scale 16、dropout 0.05，套用在最後 16 層的 `q_proj`、`v_proj` |
| 可訓練參數 | 131 萬 |
| 訓練 | 400 步、batch 4、learning rate 1e-4，在 Apple Silicon 上約 1.8 小時 |
| 資料 | 合成資料，train 900 筆、valid 120 筆、test 150 筆，課程主題不重疊；另有 40 句人工撰寫的測試句 |

訓練資料由「已知答案的片段」組成，不含真實使用者的對話。

轉檔流程：MLX adapter 先合併回模型並解除量化，再用 llama.cpp 轉成 f16 GGUF，最後量化成 Q4_K_M。

## 評估

| 版本 | 合成測試（150） | 人工測試（40） |
| --- | --- | --- |
| 規則解析（網站原本的做法） | 54.7% | 50.0% |
| 原始千問 4B（同一份提示詞，沒有微調） | 18.0% | 22.5% |
| 微調，MLX 4-bit | 97.3% | 92.5% |
| **微調，GGUF Q4_K_M（本模型）** | **97.3%** | **90.0%** |

表中數字是「意圖和全部條件都對」的比例，JSON 格式合格率是 100%。在 Apple Silicon 上每句的中位數耗時是 0.8 秒。

已知弱點是比較模糊的說法。例如「線上實體都可以」可能被判成只要線上；「停了十年想重新練」可能被判成進階。所以網站端會再用程式驗證模型輸出的每個條件。

## 授權

基礎模型 Qwen3 採用 Apache 2.0 授權，本模型沿用。
