# Job Status Constants
# These represent the overall state of a job through its lifecycle
JOB_STATUS_QUEUED = "queued"        # Job created and waiting for processing
JOB_STATUS_PROCESSING = "processing" # Job currently being processed by worker
JOB_STATUS_COMPLETED = "completed"   # Job finished successfully
JOB_STATUS_FAILED = "failed"        # Job encountered an error
JOB_STATUS_EXPIRED = "expired"      # Job is too old and has been cleaned up

JOB_STATUSES = {
    JOB_STATUS_QUEUED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_EXPIRED,
}

# Job Stage Constants  
# These represent the current processing step within a job
STAGE_UPLOADING = "uploading"                       # File being uploaded to storage
STAGE_EXTRACTING_TEXT = "extracting_text"           # OCR in progress
STAGE_PARSING = "parsing"                           # Extracting medical entities
STAGE_GENERATING_EXPLANATION = "generating_explanation"  # LLM generating explanation
STAGE_FINALIZING = "finalizing"                     # Saving results and cleanup
STAGE_DONE = "done"                                 # All processing complete
STAGE_FAILED = "failed"                             # Processing failed at some stage

JOB_STAGES = {
    STAGE_UPLOADING,
    STAGE_EXTRACTING_TEXT,
    STAGE_PARSING,
    STAGE_GENERATING_EXPLANATION,
    STAGE_FINALIZING,
    STAGE_DONE,
    STAGE_FAILED,
}

DEFAULT_PROGRESS_BY_STAGE = {
    STAGE_UPLOADING: 5,
    STAGE_EXTRACTING_TEXT: 25,
    STAGE_PARSING: 45,
    STAGE_GENERATING_EXPLANATION: 70,
    STAGE_FINALIZING: 90,
    STAGE_DONE: 100,
    STAGE_FAILED: 100,
}
