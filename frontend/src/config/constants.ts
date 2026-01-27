export const API_CONFIG = {
  BASE_URL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
  POLLING_INTERVAL_MS: 2000,
  POLLING_TIMEOUT_MS: 300000, // 5 minutes
  MAX_RETRIES: 5,
  RETRY_BACKOFF_MS: 1000,
  FILE_VALIDATION: {
    MAX_SIZE_MB: 10,
    ALLOWED_TYPES: ['application/pdf', 'image/jpeg', 'image/png'],
    ALLOWED_EXTENSIONS: ['.pdf', '.jpg', '.jpeg', '.png'],
  },
  STORAGE_KEYS: {
    CURRENT_JOB_ID: 'lumen_current_job_id',
    JOB_START_TIME: 'lumen_job_start_time',
  },
} as const;
