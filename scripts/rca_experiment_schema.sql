-- RCA Experiment Platform schema v1.0
-- Target DB: MySQL 8.x
-- Usage:
--   mysql -u<user> -p<password> <database> < scripts/rca_experiment_schema.sql

CREATE TABLE IF NOT EXISTS PR_RCA_INPUT (
    input_id BIGINT NOT NULL AUTO_INCREMENT,
    input_name VARCHAR(255) NOT NULL DEFAULT '',
    text LONGTEXT NOT NULL,
    hash CHAR(64) NOT NULL,
    priority INT NOT NULL DEFAULT 0,
    update_dt TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (input_id),
    UNIQUE KEY uq_pr_rca_input_hash (hash),
    KEY idx_pr_rca_input_priority (priority),
    KEY idx_pr_rca_input_update_dt (update_dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS PR_RCA_PROMPT (
    prompt_id BIGINT NOT NULL AUTO_INCREMENT,
    text LONGTEXT NOT NULL,
    hash CHAR(64) NOT NULL,
    priority INT NOT NULL DEFAULT 0,
    update_dt TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (prompt_id),
    UNIQUE KEY uq_pr_rca_prompt_hash (hash),
    KEY idx_pr_rca_prompt_priority (priority),
    KEY idx_pr_rca_prompt_update_dt (update_dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS PR_RCA_RUN (
    run_id BIGINT NOT NULL AUTO_INCREMENT,
    run_mode VARCHAR(20) NOT NULL,
    update_dt TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id),
    KEY idx_pr_rca_run_mode (run_mode),
    KEY idx_pr_rca_run_update_dt (update_dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS PR_RCA_RESULT (
    result_id BIGINT NOT NULL AUTO_INCREMENT,
    text LONGTEXT NOT NULL,
    hallucination_score DOUBLE NULL,
    over_confidence_score DOUBLE NULL,
    evidence_missing_score DOUBLE NULL,
    domain_bias_score DOUBLE NULL,
    evaluation_comment TEXT NULL,
    priority INT NOT NULL DEFAULT 0,
    update_dt TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (result_id),
    KEY idx_pr_rca_result_priority (priority),
    KEY idx_pr_rca_result_update_dt (update_dt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS PR_RCA_STEP (
    step_id BIGINT NOT NULL AUTO_INCREMENT,
    step_type VARCHAR(50) NOT NULL,
    run_id BIGINT NOT NULL,
    input_id BIGINT NOT NULL,
    prompt_id BIGINT NOT NULL,
    result_id BIGINT NULL,
    priority INT NOT NULL DEFAULT 0,
    update_dt TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (step_id),
    KEY idx_pr_rca_step_run_id (run_id),
    KEY idx_pr_rca_step_input_id (input_id),
    KEY idx_pr_rca_step_prompt_id (prompt_id),
    KEY idx_pr_rca_step_result_id (result_id),
    KEY idx_pr_rca_step_type (step_type),
    CONSTRAINT fk_pr_rca_step_run
        FOREIGN KEY (run_id) REFERENCES PR_RCA_RUN (run_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_pr_rca_step_input
        FOREIGN KEY (input_id) REFERENCES PR_RCA_INPUT (input_id),
    CONSTRAINT fk_pr_rca_step_prompt
        FOREIGN KEY (prompt_id) REFERENCES PR_RCA_PROMPT (prompt_id),
    CONSTRAINT fk_pr_rca_step_result
        FOREIGN KEY (result_id) REFERENCES PR_RCA_RESULT (result_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
