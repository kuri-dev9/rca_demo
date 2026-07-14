-- RCA Lab migration for existing RCA Experiment Platform databases.
-- MySQL 8.x

DROP PROCEDURE IF EXISTS pr_rca_add_column_if_missing;

DELIMITER //
CREATE PROCEDURE pr_rca_add_column_if_missing(
    IN p_table_name VARCHAR(64),
    IN p_column_name VARCHAR(64),
    IN p_column_ddl TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = p_table_name
          AND COLUMN_NAME = p_column_name
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE ', p_table_name, ' ADD COLUMN ', p_column_ddl);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END//
DELIMITER ;

CALL pr_rca_add_column_if_missing('PR_RCA_RUN', 'model', 'model VARCHAR(100) NULL');

CALL pr_rca_add_column_if_missing('PR_RCA_RESULT', 'accuracy_score', 'accuracy_score DOUBLE NULL');
CALL pr_rca_add_column_if_missing('PR_RCA_RESULT', 'reasoning_score', 'reasoning_score DOUBLE NULL');
CALL pr_rca_add_column_if_missing('PR_RCA_RESULT', 'evidence_score', 'evidence_score DOUBLE NULL');
CALL pr_rca_add_column_if_missing('PR_RCA_RESULT', 'actionability_score', 'actionability_score DOUBLE NULL');
CALL pr_rca_add_column_if_missing('PR_RCA_RESULT', 'accuracy_comment', 'accuracy_comment TEXT NULL');
CALL pr_rca_add_column_if_missing('PR_RCA_RESULT', 'reasoning_comment', 'reasoning_comment TEXT NULL');
CALL pr_rca_add_column_if_missing('PR_RCA_RESULT', 'evidence_comment', 'evidence_comment TEXT NULL');
CALL pr_rca_add_column_if_missing('PR_RCA_RESULT', 'actionability_comment', 'actionability_comment TEXT NULL');

DROP PROCEDURE pr_rca_add_column_if_missing;

CREATE TABLE IF NOT EXISTS PR_RCA_HUMAN_EVAL (
    evaluation_id BIGINT NOT NULL AUTO_INCREMENT,
    result_id BIGINT NOT NULL,
    rating VARCHAR(20) NOT NULL,
    selected_result_id BIGINT NULL,
    comment TEXT NULL,
    evaluator VARCHAR(100) NOT NULL DEFAULT 'human',
    update_dt TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (evaluation_id),
    KEY idx_pr_rca_human_eval_result_id (result_id),
    KEY idx_pr_rca_human_eval_selected_result_id (selected_result_id),
    KEY idx_pr_rca_human_eval_rating (rating),
    CONSTRAINT fk_pr_rca_human_eval_result
        FOREIGN KEY (result_id) REFERENCES PR_RCA_RESULT (result_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_pr_rca_human_eval_selected_result
        FOREIGN KEY (selected_result_id) REFERENCES PR_RCA_RESULT (result_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS PR_RCA_JUDGE (
    judge_id BIGINT NOT NULL AUTO_INCREMENT,
    result_id BIGINT NOT NULL,
    judge_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SUCCESS',
    total_score DOUBLE NULL,
    accuracy_score DOUBLE NULL,
    reasoning_score DOUBLE NULL,
    evidence_score DOUBLE NULL,
    actionability_score DOUBLE NULL,
    accuracy_comment TEXT NULL,
    reasoning_comment TEXT NULL,
    evidence_comment TEXT NULL,
    actionability_comment TEXT NULL,
    judge_comment TEXT NULL,
    raw_response LONGTEXT NULL,
    evaluator VARCHAR(100) NULL,
    update_dt TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (judge_id),
    KEY idx_pr_rca_judge_result_id (result_id),
    KEY idx_pr_rca_judge_type (judge_type),
    CONSTRAINT fk_pr_rca_judge_result
        FOREIGN KEY (result_id) REFERENCES PR_RCA_RESULT (result_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
