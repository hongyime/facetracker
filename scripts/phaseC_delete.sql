-- !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
-- ONE-TIME SCRIPT — ALREADY RAN 2026-05-27. DO NOT RUN AGAIN.
-- Re-running will create duplicate audit rows and may delete
-- images.failed rows introduced after the original run date.
-- Kept for forensic reference only.
-- !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
--
-- Phase C orphan cleanup: delete the 54,044 inert rows that orphan recovery
-- marked status='failed' with error_message='recovery: ...' because they had
-- face_count=0 and never finished processing. They have no FK children
-- (verified before run). The row itself is the only thing being removed.
--
-- Audit table is preserved across runs so we can forensically inspect what
-- was deleted (image_id, file_path, deleted_at) if anything turns up later.

BEGIN;

CREATE TABLE IF NOT EXISTS images_phaseC_delete_audit (
  image_id    INT,
  file_path   TEXT,
  deleted_at  TIMESTAMP DEFAULT NOW()
);

INSERT INTO images_phaseC_delete_audit (image_id, file_path)
  SELECT id, file_path
    FROM images
   WHERE status='failed'
     AND error_message LIKE 'recovery: %';

DELETE FROM images
 WHERE status='failed'
   AND error_message LIKE 'recovery: %';

COMMIT;

SELECT 'audit_total: '||COUNT(*) FROM images_phaseC_delete_audit;
SELECT 'remaining_failed: '||COUNT(*) FROM images WHERE status='failed';
SELECT 'completed: '||COUNT(*) FROM images WHERE status='completed';
SELECT 'pending: '||COUNT(*) FROM images WHERE status='pending';
