-- Align the intermediate 12-table schema to the FYP ERD/data dictionary.
-- Source state expected: tables are already singular, but still use generic
-- columns such as id/name/email/content/filename.

ALTER TABLE `requester` RENAME COLUMN `id` TO `requester_id`;
ALTER TABLE `requester` RENAME COLUMN `name` TO `requester_name`;
ALTER TABLE `requester` RENAME COLUMN `email` TO `requester_email`;
ALTER TABLE `requester` RENAME COLUMN `phone` TO `requester_phone`;

ALTER TABLE `technician` RENAME COLUMN `id` TO `technician_id`;
ALTER TABLE `technician` RENAME COLUMN `name` TO `technician_name`;
ALTER TABLE `technician` RENAME COLUMN `email` TO `technician_email`;
ALTER TABLE `technician` RENAME COLUMN `password_hash` TO `technician_password_hash`;
ALTER TABLE `technician` RENAME COLUMN `is_active` TO `active_status`;
ALTER TABLE `technician` RENAME COLUMN `availability` TO `availability_status`;
ALTER TABLE `technician` ADD COLUMN `technician_phone` VARCHAR(50) NULL AFTER `technician_email`;

ALTER TABLE `admin` RENAME COLUMN `id` TO `admin_id`;
ALTER TABLE `admin` RENAME COLUMN `name` TO `admin_name`;
ALTER TABLE `admin` RENAME COLUMN `email` TO `admin_email`;
ALTER TABLE `admin` RENAME COLUMN `password_hash` TO `admin_password_hash`;
ALTER TABLE `admin` RENAME COLUMN `is_active` TO `active_status`;

ALTER TABLE `category` RENAME COLUMN `id` TO `category_id`;
ALTER TABLE `category` RENAME COLUMN `name` TO `category_name`;

ALTER TABLE `priority` RENAME COLUMN `id` TO `priority_id`;
ALTER TABLE `priority` RENAME COLUMN `name` TO `priority_name`;

ALTER TABLE `status` RENAME COLUMN `id` TO `status_id`;
ALTER TABLE `status` RENAME COLUMN `name` TO `status_name`;

ALTER TABLE `ticket` RENAME COLUMN `id` TO `ticket_id`;
ALTER TABLE `ticket` RENAME COLUMN `ai_solution_suggestion` TO `ai_suggestion`;

ALTER TABLE `message` RENAME COLUMN `id` TO `message_id`;
ALTER TABLE `message` RENAME COLUMN `content` TO `message_text`;
ALTER TABLE `message`
  ADD COLUMN `requester_id` INT NULL AFTER `ticket_id`,
  ADD COLUMN `technician_id` INT NULL AFTER `requester_id`;

UPDATE `message` m
JOIN `ticket` t ON t.`ticket_id` = m.`ticket_id`
SET m.`requester_id` = t.`requester_id`
WHERE m.`author_role` = 'Requester' AND m.`requester_id` IS NULL;

UPDATE `message`
SET `technician_id` = `author_id`
WHERE `author_role` = 'Technician'
  AND `author_id` IS NOT NULL
  AND `technician_id` IS NULL;

ALTER TABLE `message`
  DROP COLUMN `author_role`,
  DROP COLUMN `author_id`,
  ADD CONSTRAINT `fk_message_requester`
    FOREIGN KEY (`requester_id`) REFERENCES `requester` (`requester_id`),
  ADD CONSTRAINT `fk_message_technician`
    FOREIGN KEY (`technician_id`) REFERENCES `technician` (`technician_id`),
  ADD CONSTRAINT `chk_message_sender_not_both`
    CHECK (`requester_id` IS NULL OR `technician_id` IS NULL);

ALTER TABLE `attachment` RENAME COLUMN `id` TO `attachment_id`;
ALTER TABLE `attachment` RENAME COLUMN `filename` TO `attachment_name`;
ALTER TABLE `attachment` RENAME COLUMN `path` TO `attachment_path`;
ALTER TABLE `attachment` RENAME COLUMN `sha256` TO `attachment_hash`;
ALTER TABLE `attachment` RENAME COLUMN `created_at` TO `uploaded_at`;
ALTER TABLE `attachment`
  ADD COLUMN `uploaded_by_requester_id` INT NULL AFTER `ticket_id`,
  ADD COLUMN `uploaded_by_technician_id` INT NULL AFTER `uploaded_by_requester_id`;

UPDATE `attachment` a
JOIN `ticket` t ON t.`ticket_id` = a.`ticket_id`
SET a.`uploaded_by_requester_id` = t.`requester_id`
WHERE a.`uploaded_by_role` = 'Requester'
  AND a.`uploaded_by_requester_id` IS NULL;

UPDATE `attachment`
SET `uploaded_by_technician_id` = `uploaded_by_id`
WHERE `uploaded_by_role` = 'Technician'
  AND `uploaded_by_id` IS NOT NULL
  AND `uploaded_by_technician_id` IS NULL;

ALTER TABLE `attachment`
  DROP COLUMN `uploaded_by_role`,
  DROP COLUMN `uploaded_by_id`,
  ADD CONSTRAINT `fk_attachment_requester`
    FOREIGN KEY (`uploaded_by_requester_id`) REFERENCES `requester` (`requester_id`),
  ADD CONSTRAINT `fk_attachment_technician`
    FOREIGN KEY (`uploaded_by_technician_id`) REFERENCES `technician` (`technician_id`),
  ADD CONSTRAINT `chk_attachment_uploader_not_both`
    CHECK (`uploaded_by_requester_id` IS NULL OR `uploaded_by_technician_id` IS NULL);

ALTER TABLE `health_check` RENAME COLUMN `id` TO `health_check_id`;
ALTER TABLE `health_check` RENAME COLUMN `checklist_json` TO `health_check_checklist`;
ALTER TABLE `health_check` RENAME COLUMN `result` TO `health_check_result`;
ALTER TABLE `health_check` RENAME COLUMN `notes` TO `health_check_notes`;
ALTER TABLE `health_check` RENAME COLUMN `created_at` TO `checked_at`;

ALTER TABLE `closure_confirmation` RENAME COLUMN `id` TO `confirmation_id`;
ALTER TABLE `closure_confirmation` RENAME COLUMN `signature_name` TO `e_sign`;
ALTER TABLE `closure_confirmation` RENAME COLUMN `status` TO `confirmation_status`;
ALTER TABLE `closure_confirmation` ADD COLUMN `requester_id` INT NULL AFTER `ticket_id`;

UPDATE `closure_confirmation` c
JOIN `ticket` t ON t.`ticket_id` = c.`ticket_id`
SET c.`requester_id` = t.`requester_id`
WHERE c.`requester_id` IS NULL;

ALTER TABLE `closure_confirmation`
  ADD INDEX `ix_closure_confirmation_ticket_id` (`ticket_id`);
ALTER TABLE `closure_confirmation` DROP INDEX `ticket_id`;
ALTER TABLE `closure_confirmation`
  MODIFY COLUMN `requester_id` INT NOT NULL,
  ADD CONSTRAINT `fk_closure_requester`
    FOREIGN KEY (`requester_id`) REFERENCES `requester` (`requester_id`);

ALTER TABLE `admin_action_log` RENAME COLUMN `id` TO `log_id`;
ALTER TABLE `admin_action_log` RENAME COLUMN `action` TO `action_type`;
ALTER TABLE `admin_action_log` RENAME COLUMN `details` TO `action_reason`;
ALTER TABLE `admin_action_log` RENAME COLUMN `created_at` TO `action_time`;
ALTER TABLE `admin_action_log` ADD COLUMN `ticket_id` INT NULL AFTER `admin_id`;

UPDATE `admin_action_log`
SET `ticket_id` = `target_id`
WHERE `target_type` = 'ticket' AND `ticket_id` IS NULL;

ALTER TABLE `admin_action_log`
  DROP COLUMN `target_type`,
  DROP COLUMN `target_id`,
  ADD CONSTRAINT `fk_admin_action_log_ticket`
    FOREIGN KEY (`ticket_id`) REFERENCES `ticket` (`ticket_id`);
