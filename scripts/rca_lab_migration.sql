-- RCA Lab migration for existing RCA Experiment Platform databases.
-- MySQL 8.x

ALTER TABLE PR_RCA_RESULT ADD COLUMN IF NOT EXISTS accuracy_score DOUBLE NULL;
ALTER TABLE PR_RCA_RESULT ADD COLUMN IF NOT EXISTS reasoning_score DOUBLE NULL;
ALTER TABLE PR_RCA_RESULT ADD COLUMN IF NOT EXISTS evidence_score DOUBLE NULL;
ALTER TABLE PR_RCA_RESULT ADD COLUMN IF NOT EXISTS actionability_score DOUBLE NULL;
ALTER TABLE PR_RCA_RESULT ADD COLUMN IF NOT EXISTS accuracy_comment TEXT NULL;
ALTER TABLE PR_RCA_RESULT ADD COLUMN IF NOT EXISTS reasoning_comment TEXT NULL;
ALTER TABLE PR_RCA_RESULT ADD COLUMN IF NOT EXISTS evidence_comment TEXT NULL;
ALTER TABLE PR_RCA_RESULT ADD COLUMN IF NOT EXISTS actionability_comment TEXT NULL;

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
