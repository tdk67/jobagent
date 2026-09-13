-- 004_interaction_reasoning.sql: Add reasoning and intent columns to email_interactions

ALTER TABLE email_interactions ADD COLUMN reasoning TEXT;
ALTER TABLE email_interactions ADD COLUMN intent TEXT;
