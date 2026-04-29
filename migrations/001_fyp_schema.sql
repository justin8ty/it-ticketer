-- One-time MySQL 8 migration from the current 7-table prototype schema
-- to the FYP schema. Run against the existing ticketdb database.
-- The Flask app also has an idempotent migrate_schema() helper with the
-- same migration path for local development startup.

DROP TABLE IF EXISTS `ai_results`;
DROP TABLE IF EXISTS `health_check_templates`;

RENAME TABLE
  `admins` TO `admin`,
  `technicians` TO `technician`,
  `tickets` TO `ticket`,
  `messages` TO `message`,
  `attachments` TO `attachment`,
  `health_checks` TO `health_check`,
  `closure_confirmations` TO `closure_confirmation`;

CREATE TABLE `requester` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(255) NOT NULL,
  `email` VARCHAR(255) NOT NULL,
  `phone` VARCHAR(50) NULL,
  `telegram_chat_id` VARCHAR(64) NULL,
  `notification_preference` VARCHAR(20) NOT NULL DEFAULT 'BOTH',
  `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_requester_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `category` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(100) NOT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_category_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `priority` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(50) NOT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_priority_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `status` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(50) NOT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_status_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `admin_action_log` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `admin_id` INT NOT NULL,
  `action` VARCHAR(100) NOT NULL,
  `target_type` VARCHAR(100) NOT NULL,
  `target_id` INT NULL,
  `details` TEXT NULL,
  `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_admin_action_log_admin_id` (`admin_id`),
  CONSTRAINT `fk_admin_action_log_admin`
    FOREIGN KEY (`admin_id`) REFERENCES `admin` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO `category` (`name`, `sort_order`) VALUES
  ('Network', 1),
  ('Hardware', 2),
  ('Software', 3),
  ('Printer', 4),
  ('Account', 5),
  ('Other', 6);

INSERT INTO `priority` (`name`, `sort_order`) VALUES
  ('Low', 1),
  ('Medium', 2),
  ('High', 3),
  ('Critical', 4);

INSERT INTO `status` (`name`, `sort_order`) VALUES
  ('NEW', 1),
  ('IN_PROGRESS', 2),
  ('PENDING_CONFIRMATION', 3),
  ('CLOSED', 4),
  ('REOPENED', 5);

INSERT IGNORE INTO `category` (`name`, `sort_order`)
SELECT DISTINCT TRIM(`category`), 999
FROM `ticket`
WHERE `category` IS NOT NULL AND TRIM(`category`) <> '';

INSERT IGNORE INTO `priority` (`name`, `sort_order`)
SELECT DISTINCT TRIM(`priority`), 999
FROM `ticket`
WHERE `priority` IS NOT NULL AND TRIM(`priority`) <> '';

INSERT IGNORE INTO `status` (`name`, `sort_order`)
SELECT DISTINCT TRIM(`status`), 999
FROM `ticket`
WHERE `status` IS NOT NULL AND TRIM(`status`) <> '';

ALTER TABLE `admin`
  ADD COLUMN `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  ADD COLUMN `updated_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE `technician`
  ADD COLUMN `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  ADD COLUMN `updated_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE `closure_confirmation`
  ADD COLUMN `requested_at` DATETIME NULL,
  ADD COLUMN `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  ADD COLUMN `updated_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE `ticket` RENAME COLUMN `token` TO `tracking_token`;
ALTER TABLE `ticket` RENAME COLUMN `ai_suggested_solution` TO `ai_solution_suggestion`;

ALTER TABLE `ticket`
  ADD COLUMN `requester_id` INT NULL,
  ADD COLUMN `category_id` INT NULL,
  ADD COLUMN `priority_id` INT NULL,
  ADD COLUMN `status_id` INT NULL;

ALTER TABLE `requester` ADD COLUMN `migration_ticket_id` INT NULL;

INSERT INTO `requester`
  (`name`, `email`, `phone`, `telegram_chat_id`, `notification_preference`, `migration_ticket_id`)
SELECT
  COALESCE(NULLIF(TRIM(`requester_name`), ''), 'Unknown Requester'),
  COALESCE(NULLIF(TRIM(`requester_email`), ''), CONCAT('unknown+ticket', `id`, '@local.invalid')),
  `requester_phone`,
  `requester_telegram_chat_id`,
  COALESCE(NULLIF(TRIM(`requester_notification_preference`), ''), 'BOTH'),
  `id`
FROM `ticket`;

UPDATE `ticket` t
JOIN `requester` r ON r.`migration_ticket_id` = t.`id`
SET t.`requester_id` = r.`id`;

ALTER TABLE `requester` DROP COLUMN `migration_ticket_id`;

UPDATE `ticket` t
JOIN `category` c ON c.`name` = COALESCE(NULLIF(TRIM(t.`category`), ''), 'Other')
SET t.`category_id` = c.`id`;

UPDATE `ticket` t
JOIN `priority` p ON p.`name` = COALESCE(NULLIF(TRIM(t.`priority`), ''), 'Medium')
SET t.`priority_id` = p.`id`;

UPDATE `ticket` t
JOIN `status` s ON s.`name` = COALESCE(NULLIF(TRIM(t.`status`), ''), 'NEW')
SET t.`status_id` = s.`id`;

ALTER TABLE `ticket`
  MODIFY COLUMN `requester_id` INT NOT NULL,
  MODIFY COLUMN `category_id` INT NOT NULL,
  MODIFY COLUMN `priority_id` INT NOT NULL,
  MODIFY COLUMN `status_id` INT NOT NULL,
  DROP COLUMN `requester_name`,
  DROP COLUMN `requester_email`,
  DROP COLUMN `requester_phone`,
  DROP COLUMN `requester_telegram_chat_id`,
  DROP COLUMN `requester_notification_preference`,
  DROP COLUMN `category`,
  DROP COLUMN `priority`,
  DROP COLUMN `status`,
  ADD CONSTRAINT `fk_ticket_requester`
    FOREIGN KEY (`requester_id`) REFERENCES `requester` (`id`),
  ADD CONSTRAINT `fk_ticket_category`
    FOREIGN KEY (`category_id`) REFERENCES `category` (`id`),
  ADD CONSTRAINT `fk_ticket_priority`
    FOREIGN KEY (`priority_id`) REFERENCES `priority` (`id`),
  ADD CONSTRAINT `fk_ticket_status`
    FOREIGN KEY (`status_id`) REFERENCES `status` (`id`);
