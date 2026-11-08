# 共用測試站維運

2026-10-28 已在目前維運者 Mac 安裝 current-user launchd：每日台北時間 09:00 備份、保留最近 7 份成功備份，每小時監控一次。Gmail 測試信已由 SMTP 接受；寄件與收件均為 `a55990a00@gmail.com`。

電腦必須開機並登入此使用者，Docker Desktop 必須運行，網路亦須可用。這不是全天候雲端監控：本機關機時不會執行或寄出警報。若需全天候保障，應將同一套 CLI 移至常駐主機。

## 設定與檔案

- 私密設定：根目錄 `.env.cloud.json`、`.env.ops.json`；Gmail 應用程式密碼：`.env.ops.gmail-app-password`。均不提交 Git，不在聊天或團隊文件分享。
- 設定範本：[.env.ops.example.json](../.env.ops.example.json)。更改收件人後可執行一次 `notify-test` 驗證。
- 備份：`db-backups/managed/263aee2fd1f82c8f/`。
- 狀態與報告：`db-backups/managed/state/263aee2fd1f82c8f/`，含 `latest-report.json`、`backup-status.json`、`restore-status.json`、`notification-outbox.json` 與排程日誌。
- 排程執行碼及獨立 Python 環境：`~/Library/Application Support/AIPE04Ops/`。切換 Git 分支不會移除已安裝程式，但私密設定檔與原路徑仍須保留。修改維運程式後須重新執行 `install-schedule` 發布新版本；排程跑的是發布當時的程式，schema 契約也要這樣更新。

## 操作指令

在專案根目錄執行，秘密不需要出現在命令參數：

```sh
.venv/bin/python -m scripts.ops.cli --config .env.ops.json backup
.venv/bin/python -m scripts.ops.cli --config .env.ops.json monitor
.venv/bin/python -m scripts.ops.cli --config .env.ops.json notify-test
.venv/bin/python -m scripts.ops.cli --config .env.ops.json notify-flush
.venv/bin/python -m scripts.ops.cli --config .env.ops.json install-schedule
.venv/bin/python -m scripts.ops.cli --config .env.ops.json uninstall-schedule
```

驗證或隔離還原指定備份時，將下列路徑替換為實際備份目錄：

```sh
.venv/bin/python -m scripts.ops.cli --config .env.ops.json verify --bundle db-backups/managed/263aee2fd1f82c8f/20261028T064323Z-af240784
.venv/bin/python -m scripts.ops.cli --config .env.ops.json restore-check --bundle db-backups/managed/263aee2fd1f82c8f/20261028T064323Z-af240784
```

`restore-check` 只建立全新、無外部網路、無主機連接埠的 Docker PostgreSQL 容器；核對完成後移除該容器，不會還原到共享資料庫。應在重大資料修改前手動備份，並定期執行隔離還原。

## 備份範圍與保留

PostgreSQL 使用同一個唯讀 snapshot 備份 `public` schema、資料、資料表筆數及檔案引用。另完整備份 `teaching-files`、`profile-images`、`teacher-proofs` 三個 bucket，保存 SHA-256 與物件 metadata。只有版本 metadata 充分且本機內容雜湊相符時才重用舊物件，降低重複下載；每份完成備份仍可獨立驗證。

任何必要物件消失或驗證失敗都不發布成功備份，也不清理舊備份。保留規則只刪除此工具建立、同來源且已完成的備份；不刪手工備份、其他專案或雲端資料。備份不包含 Supabase Auth、平台設定或所有基礎設施設定，不能視為整個 Supabase 專案的完整災難復原映像。

新增 bucket 時須明確納入備份範圍；新增資料庫檔案欄位時須同步更新 `scripts/ops/database_refs.py`。備份留在本機磁碟，仍應另規劃第二份受保護副本，以防本機磁碟損壞。

## 監控與 Gmail

監控檢查 DB、所有 Storage bucket、網站健康、備份年齡、清理佇列及評分任務。容量預算預設 DB 500 MB、Storage 1 GB，達 70% 警告、85% 嚴重；備份超過 36 小時提醒。預算可設定，屬使用量觀測，並非供應商帳單或流量監測；實際額度依 [Supabase 方案](https://supabase.com/pricing) 為準。

探測失敗會標示未知，不會假裝零用量或錯誤解除既有警報。同嚴重度條件每 24 小時最多新增一次提醒；升級與恢復立即產生事件。Gmail 使用固定 SMTP 465 及完整 TLS 憑證驗證，僅寄維運摘要，不附加備份或憑證。寄送失敗保留待送事件，下次監控重試；極端情況可能重複寄送。

## 已驗證（2026-10-28）

26 個維運測試通過；實際備份與隔離還原核對 28 張表、5 個物件及 5 筆檔案引用。已人工觸發 launchd 工作驗證。這一階段沒有變更共用站 schema 或部署應用程式；獨立音訊評分 worker 仍留待下一階段。

## CI 與 schema 升級

CI／PR 合併順序見 [CI 與 PR 手冊](ci-and-pr.md)。備份欄位契約（`scripts/ops/database_refs.py`）明確支援 `016_storage_cleanup` 到 `025_course_chat_starters`；`017_merge_storage_audio` 起納入 `practice_feedbacks.score_sheet_path`。未知 revision 或多個 migration head 會拒絕備份，避免漏驗檔案引用。升級其他 schema 前需先更新此契約。
