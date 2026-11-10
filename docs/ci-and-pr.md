# CI 與 PR 合併流程

每個 PR 與 main push 執行：

| 檢查 | 工作流程 | 驗證內容 |
| --- | --- | --- |
| postgres-tests | `database.yml` | PostgreSQL 17 空庫 migration、完整 pytest（含維運測試）、最後 revision |
| frontend | `quality.yml` | Node 24、npm ci、lint-check、TypeScript 與 production build |
| source-safety | `quality.yml` | 拒絕追蹤私人 env／備份／金鑰，Gitleaks 遮蔽掃描本次 commit range |
| ops-lint | `operations.yml` | 用 ruff 檢查 `scripts/ops`、`tests/ops` 的格式與靜態錯誤 |

所有工作只授予 contents:read，沒有雲端、Gmail 或 LLM secrets。DB 是 runner 上可丟棄的 PostgreSQL；Storage/SMTP 測試使用 mock。CI 不會備份正式資料、寄信、執行 macOS 排程或部署 Render。

Gitleaks 掃描 PR base 到測試 merge commit 的新增歷史，以及 main push 的 before 到 HEAD；首次 push 無 before 時掃描 HEAD 可達歷史。它不是既有完整歷史稽核，也不能保證識別所有秘密。現有 `frontend/.env.development` 只有公開的 Vite 開關，允許追蹤；私人 `.env.*` 仍應保持 ignored。範本也仍受內容掃描。

## 合併

未設定自動合併。workflow 本身不等於強制門禁：2026-11-01 查詢時，`main` 沒有 Branch protection，也沒有 Ruleset。要強制時，請 repository 管理者設定 main 必須經 PR、至少一位 reviewer，並要求上述四項檢查。

## CD 後續

`render.yaml` 仍為 `autoDeployTrigger: off`，線上測試站採人工部署。部署前先檢查目標版本、執行備份，再部署與驗收。之後可考慮將 Render 連結分支改為 main，Auto-Deploy 改為 After CI Checks Pass（Blueprint 值 `checksPass`）。[Render 文件](https://render.com/docs/deploys#integrating-with-ci) 說明任一 CI 失敗時不自動部署。

升級共用測試站時，`deploy/start.sh` 會在啟動時執行 Alembic upgrade head。不要只換程式而跳過 migration；不要把新 ORM 連到舊 schema 做正式操作。維運工具的 schema 欄位契約（`scripts/ops/database_refs.py`）也須同步，目前支援到 `026_course_delivery_hybrid`。`024_pgvector_rag` 需要 pgvector 擴充功能：本機與 CI 使用 `pgvector/pgvector:0.8.1-pg17-trixie`，Supabase 內建（`extensions` schema）。
