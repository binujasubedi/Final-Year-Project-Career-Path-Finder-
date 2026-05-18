from typing import Optional, Dict, Any, List
from datetime import datetime
from supabase import Client
from .supabase_client import get_supabase_client
import json

class ResumeRepository:
    """
    Handles all database operations for resumes
    """

    def __init__(self, client: Optional[Client] = None):
        self.client = client or get_supabase_client()

    def _json_ready(self, value: Any) -> Any:
        """
        Convert tuples and other JSON-compatible Python values into plain JSON data.
        """
        return json.loads(json.dumps(value))

    def save_resume(
        self,
        user_id: str,
        filename: str,
        file_type: str,
        raw_text: str,
        parsed_data: Dict[str, Any],
        file_size: int,
        analysis_result: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Save a parsed resume to the database
        """
        try:
            resume_data = {
                "user_id": user_id,
                "filename": filename,
                "file_type": file_type,
                "raw_text": raw_text,
                "parsed_skills": self._json_ready(parsed_data.get("skills", [])),
                "parsed_education": self._json_ready(parsed_data.get("education", [])),
                "parsed_experience": self._json_ready(parsed_data.get("experience", [])),
                "file_size": file_size
            }

            if analysis_result is not None:
                resume_data["analysis_result"] = self._json_ready(analysis_result)

            try:
                response = self.client.table("resumes").insert(resume_data).execute()
            except Exception as e:
                if "analysis_result" not in str(e):
                    raise

                resume_data.pop("analysis_result", None)
                response = self.client.table("resumes").insert(resume_data).execute()

            if response.data:
                return response.data[0]
            return None

        except Exception as e:
            print(f"Error saving resume: {e}")
            return None

    def get_user_resumes(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all resumes for a specific user
        """
        try:
            response = self.client.table("resumes").select("*").eq(
                "user_id", user_id
            ).order("upload_date", desc=True).execute()

            if response.data:
                for resume in response.data:
                    if isinstance(resume.get("parsed_skills"), str):
                        resume["parsed_skills"] = json.loads(resume["parsed_skills"])
                    if isinstance(resume.get("parsed_education"), str):
                        resume["parsed_education"] = json.loads(resume["parsed_education"])
                    if isinstance(resume.get("parsed_experience"), str):
                        resume["parsed_experience"] = json.loads(resume["parsed_experience"])
                    if isinstance(resume.get("analysis_result"), str):
                        resume["analysis_result"] = json.loads(resume["analysis_result"])

                return response.data
            return []

        except Exception as e:
            print(f"Error fetching resumes: {e}")
            return []

    def get_resume_by_id(self, resume_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific resume by ID
        """
        try:
            response = self.client.table("resumes").select("*").eq(
                "id", resume_id
            ).eq("user_id", user_id).maybeSingle().execute()

            if response.data:
                resume = response.data
                if isinstance(resume.get("parsed_skills"), str):
                    resume["parsed_skills"] = json.loads(resume["parsed_skills"])
                if isinstance(resume.get("parsed_education"), str):
                    resume["parsed_education"] = json.loads(resume["parsed_education"])
                if isinstance(resume.get("parsed_experience"), str):
                    resume["parsed_experience"] = json.loads(resume["parsed_experience"])
                if isinstance(resume.get("analysis_result"), str):
                    resume["analysis_result"] = json.loads(resume["analysis_result"])

                return resume
            return None

        except Exception as e:
            print(f"Error fetching resume: {e}")
            return None

    def update_resume_analysis(
        self,
        resume_id: str,
        user_id: str,
        raw_text: str,
        parsed_data: Dict[str, Any],
        analysis_result: Dict[str, Any]
    ) -> bool:
        """
        Update stored resume parsing and full analysis payload.
        """
        try:
            resume_data = {
                "raw_text": raw_text,
                "parsed_skills": self._json_ready(parsed_data.get("skills", [])),
                "parsed_education": self._json_ready(parsed_data.get("education", [])),
                "parsed_experience": self._json_ready(parsed_data.get("experience", [])),
                "analysis_result": self._json_ready(analysis_result)
            }

            try:
                self.client.table("resumes").update(resume_data).eq(
                    "id", resume_id
                ).eq("user_id", user_id).execute()
            except Exception as e:
                if "analysis_result" not in str(e):
                    raise

                resume_data.pop("analysis_result", None)
                self.client.table("resumes").update(resume_data).eq(
                    "id", resume_id
                ).eq("user_id", user_id).execute()

            return True

        except Exception as e:
            print(f"Error updating resume analysis: {e}")
            return False

    def delete_resume(self, resume_id: str, user_id: str) -> bool:
        """
        Delete a resume
        """
        try:
            self.client.table("resumes").delete().eq(
                "id", resume_id
            ).eq("user_id", user_id).execute()

            return True

        except Exception as e:
            print(f"Error deleting resume: {e}")
            return False

    def delete_user_resumes(self, user_id: str) -> bool:
        """
        Delete all resumes for a user. Skill gap rows are removed by the DB cascade.
        """
        try:
            self.client.table("resumes").delete().eq(
                "user_id", user_id
            ).execute()

            return True

        except Exception as e:
            print(f"Error deleting user resumes: {e}")
            return False

    def save_skill_gap_analysis(
        self,
        user_id: str,
        resume_id: str,
        target_role: str,
        matched_skills: List[str],
        missing_skills: List[str],
        match_score: float
    ) -> Optional[Dict[str, Any]]:
        """
        Save skill gap analysis results
        """
        try:
            analysis_data = {
                "user_id": user_id,
                "resume_id": resume_id,
                "target_role": target_role,
                "matched_skills": self._json_ready(matched_skills),
                "missing_skills": self._json_ready(missing_skills),
                "match_score": match_score
            }

            response = self.client.table("skill_gaps").insert(analysis_data).execute()

            if response.data:
                return response.data[0]
            return None

        except Exception as e:
            error_text = str(e)
            if "target_role" not in error_text or "schema cache" not in error_text:
                print(f"Error saving skill gap analysis: {e}")
            return None

    def get_user_analyses(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent skill gap analyses for a user
        """
        try:
            response = self.client.table("skill_gaps").select("*").eq(
                "user_id", user_id
            ).order("analysis_date", desc=True).limit(limit).execute()

            if response.data:
                for analysis in response.data:
                    if isinstance(analysis.get("matched_skills"), str):
                        analysis["matched_skills"] = json.loads(analysis["matched_skills"])
                    if isinstance(analysis.get("missing_skills"), str):
                        analysis["missing_skills"] = json.loads(analysis["missing_skills"])

                return response.data
            return []

        except Exception as e:
            print(f"Error fetching analyses: {e}")
            return []

    def get_resume_statistics(self, user_id: str) -> Dict[str, Any]:
        """
        Get statistics about user's resumes
        """
        try:
            resumes = self.get_user_resumes(user_id)
            analyses = self.get_user_analyses(user_id, limit=100)

            total_resumes = len(resumes)
            total_analyses = len(analyses)
            avg_match_score = sum(a.get("match_score", 0) for a in analyses) / total_analyses if total_analyses > 0 else 0

            all_skills = set()
            stored_data_count = 0
            stored_analysis_count = 0
            for resume in resumes:
                skills = resume.get("parsed_skills", [])
                if isinstance(skills, list):
                    all_skills.update(skills)

                has_parsed_data = any([
                    resume.get("raw_text"),
                    resume.get("parsed_skills"),
                    resume.get("parsed_education"),
                    resume.get("parsed_experience")
                ])
                analysis_result = resume.get("analysis_result")
                has_analysis_result = bool(analysis_result) and analysis_result != {}

                if has_parsed_data or has_analysis_result:
                    stored_data_count += 1
                if has_analysis_result:
                    stored_analysis_count += 1

            return {
                "total_resumes": total_resumes,
                "total_analyses": total_analyses,
                "average_match_score": round(avg_match_score, 2),
                "unique_skills": len(all_skills),
                "stored_data_count": stored_data_count,
                "stored_analysis_count": stored_analysis_count,
                "most_recent_upload": resumes[0].get("upload_date") if resumes else None
            }

        except Exception as e:
            print(f"Error fetching statistics: {e}")
            return {
                "total_resumes": 0,
                "total_analyses": 0,
                "average_match_score": 0,
                "unique_skills": 0,
                "stored_data_count": 0,
                "stored_analysis_count": 0,
                "most_recent_upload": None
            }
