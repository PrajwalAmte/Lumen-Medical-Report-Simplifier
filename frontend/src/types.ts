// API Response Types
export interface UploadResponse {
  job_id: string;
  status: string;
  message: string;
  estimated_time_sec: number;
}

export interface StatusResponse {
  job_id: string;
  status: string;
  progress: number;
  stage: string;
  updated_at: string;
}

export interface AbnormalValue {
  test_name: string;
  value: string;
  normal_range: string;
  severity: "mild" | "moderate" | "severe" | "critical" | "low" | "high" | "unknown";
  what_it_means: string;
  common_causes: string[];
  health_risks?: string[];
  lifestyle_recommendations?: string[];
  dietary_recommendations?: string[];
  what_to_ask_doctor: string[];
}

export interface NormalValue {
  test_name: string;
  value: string;
  normal_range: string;
  what_it_means: string;
}

export interface PatternAnalysis {
  related_abnormalities?: string;
  potential_conditions?: string[];
  underlying_mechanisms?: string;
}

export interface LifestyleActionPlan {
  diet?: string[];
  exercise?: string[];
  habits?: string[];
  monitoring?: string[];
}

export interface Medicine {
  name: string;
  generic_name?: string | null;
  purpose: string;
  mechanism?: string;
  how_to_take: string;
  common_side_effects: string[];
  serious_side_effects?: string[];
  drug_interactions?: string[];
  precautions: string[];
  generic_alternative?: string;
  lifestyle_tips?: string[];
  cost_saving_tip?: string | null;
}

export interface InputSummary {
  document_type: string;
  detected_language: string;
  detected_hospital: string | null;
  date_of_report: string | null;
}

export interface Metadata {
  processing_time_sec: number;
  ocr_engine: string;
  llm_provider: string;
  model: string;
  cached: boolean;
}

export interface ResultResponse {
  job_id: string;
  status: string;
  disclaimer: string;
  input_summary: InputSummary;
  abnormal_values: AbnormalValue[];
  normal_values: NormalValue[];
  medicines: Medicine[];
  pattern_analysis?: PatternAnalysis;
  overall_summary: string;
  urgency_level?: "routine" | "soon" | "urgent" | "emergency";
  questions_to_ask_doctor: string[];
  next_steps: string[];
  lifestyle_action_plan?: LifestyleActionPlan;
  red_flags?: string[];
  confidence_score: number;
  metadata: Metadata;
}
