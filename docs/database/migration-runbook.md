# Alembic Migration 維運手冊

## 團隊規則

1. 已在共享環境執行過的 Migration 不可修改；修正時新增下一版。
2. Model、Migration、資料搬移、測試與資料字典放在同一個 PR。
3. 合併前確認 `alembic heads` 只有一個 head。
4. 刪欄位、改型別、重建索引與大量回填前先備份，並用接近正式資料量的副本計時。
5. 不在正式資料庫手動建表或修改 `alembic_version`。

## 日常檢查

```bash
alembic -c backend/alembic.ini current
alembic -c backend/alembic.ini heads
alembic -c backend/alembic.ini history --verbose
```

目前 `main` 的預期 head：

```text
026_course_delivery_hybrid (head)
```

之後一律以 `alembic heads` 的實際唯一 head 為準。兩條功能分支各自新增 Migration 造成多個 head 時，用 merge revision 合併（前例是 `017_merge_storage_audio`、`018_merge_availability_storage`）。

建立新版本前，先同步主分支並確認目前 head。新 Migration 的 `down_revision` 必須指向當下唯一 head。

## 本機升級

`.env` 設定本機 PostgreSQL 後執行：

```bash
alembic -c backend/alembic.ini upgrade head
```

應用程式不再執行 `Base.metadata.create_all()`；缺少 Migration 時，啟動網站不會替你補表。

## 可重現的隔離驗收

先安裝 `backend/requirements.txt`。下面使用獨立、無持久化 volume 的 PostgreSQL 17 容器（含 pgvector，`024` 需要），不使用開發資料庫：

```bash
docker run -d --name aipe04-db-test \
  -e POSTGRES_USER=test_user -e POSTGRES_PASSWORD=test_password \
  -e POSTGRES_DB=aipe04_test -p 127.0.0.1:55432:5432 pgvector/pgvector:0.8.1-pg17-trixie
docker exec aipe04-db-test pg_isready -U test_user -d aipe04_test
```

等 `pg_isready` 顯示 accepting connections 後，在 macOS／Linux 執行：

```bash
export DATABASE_URL=postgresql+psycopg://test_user:test_password@127.0.0.1:55432/aipe04_test
export TEST_DATABASE_URL="$DATABASE_URL"
export SESSION_SECRET_KEY=test-only-session-key
alembic -c backend/alembic.ini upgrade head
python -m pytest tests -q
alembic -c backend/alembic.ini current
```

Windows PowerShell 用 `$env:DATABASE_URL = "..."` 設定相同環境變數。這裡的帳密只用於可刪除的測試容器。

驗收後清除本次容器：

```bash
docker rm -f aipe04-db-test
```

測試涵蓋空庫升級到 head、009 舊路徑回填、010→009→010、推薦與檔案清理 Migration、單一 head、MIDI metadata 雙寫與失敗清理，以及完整 API 回歸。`.github/workflows/database.yml` 在 PR 與 main push 執行相同驗收；音訊評分和 LLM 在測試中使用替身。

## Migration 整合測試

破壞性測試只能使用名稱以 `_test` 結尾的獨立 PostgreSQL：

```bash
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/project_test \
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/project_test \
pytest tests/database -q
```

測試會清除測試資料庫的 `public` schema。不得把正式、開發共用或含重要資料的 URL 放進 `TEST_DATABASE_URL`；fixture 會拒絕非 PostgreSQL 及名稱不是 `_test` 的資料庫。Migration 測試不建立 API 背景評分交易，並在結束時清空測試 schema、升回 head，避免降版測試影響同一輪後續 API 測試。

## 010 參考 MIDI 上線前檢查

檢查需要回填的課程數：

```sql
SELECT COUNT(*)
FROM courses
WHERE NULLIF(btrim(reference_midi_path), '') IS NOT NULL;
```

升級後檢查 metadata 數量及漏接資料：

```sql
SELECT COUNT(*) FROM reference_midis;

SELECT c.id, c.reference_midi_path
FROM courses AS c
LEFT JOIN reference_midis AS r ON r.course_id = c.id
WHERE NULLIF(btrim(c.reference_midi_path), '') IS NOT NULL
  AND r.id IS NULL;
```

第二個查詢預期回傳 0 筆。

## 備份與還原演練

上線前由有權限的操作人員建立 custom-format 備份：

```bash
pg_dump --format=custom --file=backup-before-migration.dump DATABASE_NAME
```

備份完成不代表可以還原。團隊應定期在隔離資料庫執行：

```bash
createdb restore_drill
pg_restore --dbname=restore_drill backup-before-migration.dump
```

並記錄備份時間、檔案大小、保存位置、還原耗時及抽查結果。正式環境應使用受控帳號與秘密管理，不把密碼寫進命令、文件或 Git。

## 部署順序

1. 確認應用程式版本與唯一 Migration head。
2. 建立備份並確認最近一次還原演練有效。
3. 暫停會與結構變更衝突的背景工作。
4. 執行 `alembic -c backend/alembic.ini upgrade head`。
5. 執行 010 的回填檢查 SQL。
6. 部署同版本 FastAPI。
7. 測試登入、課程列表、MIDI 上傳／下載及練習送出。
8. 觀察錯誤率、資料庫連線、transaction rollback、磁碟與備份狀態。

## Rollback 原則

下面以 `010` 為例。目前 head 是 `020`，要回到 `009` 會連同 `011`～`020` 一起降版，新表的資料會消失，所以只適合沒有重要資料的環境。`010` 本身可執行：

```bash
alembic -c backend/alembic.ini downgrade 009_images_profile
```

這會刪除 `reference_midis`，但保留 `courses.reference_midi_path`，所以舊版下載與評分仍能使用。降級前仍要備份；新上傳的 SHA-256、原始檔名與大小只存在 metadata，降級後會失去。

資料已大量寫入、後續版本已依賴新表或事故原因不明時，優先新增向前修正的 Migration，不要直接降級或手動刪表。

## 事故處理

Migration 失敗時停止繼續部署與寫入，保存 FastAPI、Alembic 與 PostgreSQL log，記錄應用程式 commit、`alembic current`、失敗 SQL 和發生時間。依交易是否 rollback、資料是否已寫入及備份能否還原，決定向前修正或還原。
