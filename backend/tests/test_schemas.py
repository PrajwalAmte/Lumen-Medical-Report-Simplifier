import pytest
from datetime import datetime, timezone
from app.models.schemas import (
    UploadResponse, StatusResponse, ResultResponse,
    InputSummary, NormalValue, AbnormalValue, Medicine, Metadata
)


def test_upload_response_creation():
    response = UploadResponse(
        job_id="test_123",
        status="queued",
        message="File uploaded",
        estimated_time_sec=40
    )
    
    assert response.job_id == "test_123"
    assert response.status == "queued"
    assert response.estimated_time_sec == 40


def test_status_response_creation():
    now = datetime.now(timezone.utc)
    response = StatusResponse(
        job_id="test_123",
        status="processing",
        progress=50,
        stage="ocr",
        updated_at=now
    )
    
    assert response.job_id == "test_123"
    assert response.progress == 50
    assert response.stage == "ocr"


def test_result_response_creation():
    metadata = Metadata(
        processing_time_sec=30,
        ocr_engine="tesseract",
        llm_provider="openai",
        model="gpt-4",
        cached=False
    )
    
    input_summary = InputSummary(document_type="blood_test")
    
    response = ResultResponse(
        job_id="test_123",
        status="completed",
        disclaimer="Test disclaimer",
        input_summary=input_summary,
        abnormal_values=[],
        normal_values=[],
        medicines=[],
        overall_summary="Test summary",
        questions_to_ask_doctor=[],
        next_steps=[],
        confidence_score=0.85,
        metadata=metadata
    )
    
    assert response.job_id == "test_123"
    assert response.confidence_score == 0.85
    assert response.metadata.processing_time_sec == 30


def test_normal_value_creation():
    normal_value = NormalValue(
        test_name="Hemoglobin",
        value="14.5 g/dL",
        normal_range="12-16 g/dL",
        what_it_means="Normal blood oxygen carrying capacity"
    )
    
    assert normal_value.test_name == "Hemoglobin"
    assert normal_value.value == "14.5 g/dL"
    assert normal_value.normal_range == "12-16 g/dL"


def test_abnormal_value_creation():
    abnormal_value = AbnormalValue(
        test_name="Cholesterol",
        value="250 mg/dL",
        normal_range="< 200 mg/dL",
        severity="high",
        what_it_means="Elevated cholesterol levels",
        common_causes=["Diet", "Genetics"],
        what_to_ask_doctor=["Should I change my diet?"]
    )
    
    assert abnormal_value.test_name == "Cholesterol"
    assert abnormal_value.severity == "high"
    assert len(abnormal_value.common_causes) == 2


def test_medicine_creation():
    medicine = Medicine(
        name="Metformin",
        purpose="Diabetes management",
        common_side_effects=["Nausea", "Diarrhea"],
        precautions=["Take with food"]
    )
    
    assert medicine.name == "Metformin"
    assert medicine.purpose == "Diabetes management"
    assert len(medicine.common_side_effects) == 2


def test_result_response_validation():
    metadata = Metadata(
        processing_time_sec=30,
        ocr_engine="tesseract",
        llm_provider="openai",
        model="gpt-4",
        cached=False
    )
    
    input_summary = InputSummary(document_type="blood_test")
    
    response = ResultResponse(
        job_id="test_123",
        status="completed",
        disclaimer="Test disclaimer",
        input_summary=input_summary,
        abnormal_values=[],
        normal_values=[],
        medicines=[],
        overall_summary="Test summary",
        questions_to_ask_doctor=[],
        next_steps=[],
        confidence_score=0.85,
        metadata=metadata
    )
    
    assert response.confidence_score == 0.85