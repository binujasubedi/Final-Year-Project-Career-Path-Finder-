/*
  Store the complete CV analysis payload on each resume.

  Existing columns keep the commonly queried fields:
  - raw_text
  - parsed_skills
  - parsed_education
  - parsed_experience

  analysis_result keeps the full analyzer output, including:
  - predictions
  - chosen_role
  - required_skills
  - gap
  - match_score
*/

ALTER TABLE resumes
ADD COLUMN IF NOT EXISTS analysis_result jsonb DEFAULT '{}'::jsonb;
