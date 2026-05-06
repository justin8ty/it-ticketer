-- Add requester rejection and proof-of-fix metadata fields.

ALTER TABLE `attachment`
  ADD COLUMN `attachment_description` TEXT NULL AFTER `uploaded_by_technician_id`;

ALTER TABLE `closure_confirmation`
  ADD COLUMN `rejected_at` DATETIME NULL AFTER `confirmed_at`,
  ADD COLUMN `rejection_reason` TEXT NULL AFTER `rejected_at`;
