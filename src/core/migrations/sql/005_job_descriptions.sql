-- 005_job_descriptions.sql: Add job description column to applications

ALTER TABLE applications ADD COLUMN job_description_md TEXT;
