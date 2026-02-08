from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class UploadResponse(BaseModel):
    """Response schema for file upload endpoint."""
    job_id: str  # Unique identifier for tracking
    status: str  # Initial job status (usually 'queued')
    message: str  # Human-readable upload confirmation
    estimated_time_sec: int  # Expected processing time


class StatusResponse(BaseModel):
    """Response schema for job status checking."""
    job_id: str
    status: str  # queued, processing, completed, failed, expired
    progress: int  # Percentage complete (0-100)
    stage: str  # Current processing stage
    updated_at: datetime  # Last update timestamp


class AbnormalValue(BaseModel):
    """Schema for abnormal test results that require attention."""
    test_name: str
    value: str  # Actual test result
    normal_range: str  # Expected normal range
    severity: str  # mild|moderate|severe|critical|low|high|unknown
    what_it_means: str  # Plain language explanation
    common_causes: List[str]  # Possible reasons for abnormal value
    what_to_ask_doctor: List[str]  # Suggested questions for doctor
    # Optional fields for enhanced explanations
    health_risks: Optional[List[str]] = None
    lifestyle_recommendations: Optional[List[str]] = None
    dietary_recommendations: Optional[List[str]] = None


class NormalValue(BaseModel):
    """Schema for normal test results."""
    test_name: str
    value: str
    normal_range: str
    what_it_means: str  # Brief explanation of what this test measures


class Medicine(BaseModel):
    name: str
    generic_name: Optional[str] = None
    purpose: str
    mechanism: Optional[str] = None
    how_to_take: Optional[str] = None
    common_side_effects: List[str] = Field(default_factory=list)
    serious_side_effects: Optional[List[str]] = None
    drug_interactions: Optional[List[str]] = None
    precautions: List[str] = Field(default_factory=list)
    generic_alternative: Optional[str] = None
    lifestyle_tips: Optional[List[str]] = None
    cost_saving_tip: Optional[str] = None


class InputSummary(BaseModel):
    document_type: str
    detected_language: Optional[str] = None
    detected_hospital: Optional[str] = None
    date_of_report: Optional[str] = None


class Metadata(BaseModel):
    processing_time_sec: int
    ocr_engine: str
    llm_provider: str
    model: str
    cached: bool


class ResultResponse(BaseModel):
    job_id: str
    status: str
    disclaimer: str
    input_summary: InputSummary
    abnormal_values: List[AbnormalValue]
    normal_values: List[NormalValue]
    medicines: List[Medicine]
    pattern_analysis: Optional[dict] = None
    overall_summary: str
    urgency_level: Optional[str] = None
    questions_to_ask_doctor: List[str]
    next_steps: List[str]
    lifestyle_action_plan: Optional[dict] = None
    red_flags: Optional[List[str]] = None
    confidence_score: float
    metadata: Metadata



class FeedbackRequest(BaseModel):
    job_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    message: str
