import { useEffect, useState, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertCircle, XCircle, Clock } from 'lucide-react';
import { ProgressBar } from '../components/ProgressBar';
import { getStatus } from '../api/lumenApi';
import { API_CONFIG } from '../config/constants';
import type { StatusResponse } from '../types';

interface PollingState {
  retryCount: number;
  startTime: number;
  lastSuccessTime: number;
}

interface ProcessingPageProps {
  jobId: string;
}

export function ProcessingPage({ jobId }: ProcessingPageProps) {
  const navigate = useNavigate();
  const { jobId: paramJobId } = useParams<{ jobId: string }>();
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedTime, setElapsedTime] = useState<number>(0);
  const pollingStateRef = useRef<PollingState>({
    retryCount: 0,
    startTime: Date.now(),
    lastSuccessTime: Date.now(),
  });
  const isMountedRef = useRef<boolean>(true);
  const intervalIdRef = useRef<NodeJS.Timeout | null>(null);
  const timerIdRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (!paramJobId) {
      navigate('/');
      return;
    }

    isMountedRef.current = true;
    pollingStateRef.current = {
      retryCount: 0,
      startTime: Date.now(),
      lastSuccessTime: Date.now(),
    };

    const pollStatus = async () => {
      if (!isMountedRef.current) return;

      try {
        const response = await getStatus(paramJobId);

        if (!isMountedRef.current) return;

        setStatus(response);
        pollingStateRef.current.retryCount = 0;
        pollingStateRef.current.lastSuccessTime = Date.now();

        if (response.status === 'completed') {
          if (intervalIdRef.current) clearInterval(intervalIdRef.current);
          if (timerIdRef.current) clearInterval(timerIdRef.current);
          navigate(`/result/${paramJobId}`);
        } else if (response.status === 'failed') {
          setError('Processing failed. Please try uploading again.');
        }
      } catch (err) {
        if (!isMountedRef.current) return;

        // If the API returned an error message, show it exactly (no friendly copy).
        if (err instanceof Error && err.message) {
          setError(err.message);
          if (intervalIdRef.current) clearInterval(intervalIdRef.current);
          return;
        }

        pollingStateRef.current.retryCount += 1;
        const timeSinceLastSuccess = Date.now() - pollingStateRef.current.lastSuccessTime;

        if (pollingStateRef.current.retryCount >= API_CONFIG.MAX_RETRIES) {
          setError(`Failed to check status after ${API_CONFIG.MAX_RETRIES} attempts. Please refresh to retry.`);
          if (intervalIdRef.current) clearInterval(intervalIdRef.current);
        } else if (timeSinceLastSuccess > API_CONFIG.POLLING_TIMEOUT_MS) {
          setError('Processing took too long (5 minutes). The job may have expired. Please try uploading again.');
          if (intervalIdRef.current) clearInterval(intervalIdRef.current);
        }
      }
    };

    pollStatus();
    intervalIdRef.current = setInterval(pollStatus, API_CONFIG.POLLING_INTERVAL_MS);

    timerIdRef.current = setInterval(() => {
      if (isMountedRef.current) {
        setElapsedTime(Math.floor((Date.now() - pollingStateRef.current.startTime) / 1000));
      }
    }, 1000);

    return () => {
      isMountedRef.current = false;
      if (intervalIdRef.current) clearInterval(intervalIdRef.current);
      if (timerIdRef.current) clearInterval(timerIdRef.current);
    };
  }, [paramJobId, navigate]);

  const handleCancel = () => {
    const confirmed = window.confirm(
      'Cancel this analysis? The job will continue processing in the background.'
    );

    if (confirmed) {
      if (intervalIdRef.current) clearInterval(intervalIdRef.current);
      if (timerIdRef.current) clearInterval(timerIdRef.current);
      navigate('/');
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-indigo-50">
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
          <div className="text-center">
            <h1 
              className="text-3xl sm:text-4xl font-bold bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent cursor-pointer hover:opacity-80 transition-opacity"
              onClick={() => navigate('/')}
            >
              Lumen
            </h1>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-center p-4 pt-12">
        <div className="bg-white rounded-lg shadow-lg p-8 max-w-md w-full">
          <h2 className="text-2xl font-bold text-gray-900 mb-2 text-center">
            Processing report...
          </h2>
          <p className="text-gray-600 text-center mb-8">
            Processing report...
          </p>

          {error ? (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex gap-3">
              <AlertCircle className="w-6 h-6 text-red-600 flex-shrink-0" />
              <div className="flex-1">
                <p className="font-semibold text-red-900">Error</p>
                <p className="text-sm text-red-700 mt-1">{error}</p>
                <button
                  onClick={() => navigate('/')}
                  className="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm font-medium"
                >
                  Back to Upload
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              <ProgressBar 
                progress={status?.progress || 0} 
                stage={status?.stage || 'processing'} 
              />

              {status && (
                <div className="bg-gray-50 rounded-lg p-4">
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <p className="text-gray-600">Job ID</p>
                      <p className="font-mono text-xs text-gray-900 break-all">
                        {status.job_id.slice(0, 12)}...
                      </p>
                    </div>
                    <div>
                      <p className="text-gray-600">Elapsed Time</p>
                      <p className="font-semibold text-blue-600">
                        {elapsedTime}s
                      </p>
                    </div>
                  </div>
                </div>
              )}

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 flex gap-2">
                <Clock className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-blue-700">
                  Typically takes 20-60 seconds. Will auto-refresh to results when ready.
                </p>
              </div>

              <button
                onClick={handleCancel}
                className="w-full px-4 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-medium flex items-center justify-center gap-2"
                aria-label="cancel-processing"
              >
                <XCircle className="w-5 h-5" />
                Cancel & Go Back
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};