import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, Info, CheckCircle } from 'lucide-react';
import { FileUploader } from '../components/FileUploader';
import { uploadFile } from '../api/lumenApi';
import { API_CONFIG } from '../config/constants';

const SESSION_STORAGE_KEYS = API_CONFIG.STORAGE_KEYS;

export const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const checkExistingJob = () => {
      const existingJobId = sessionStorage.getItem(SESSION_STORAGE_KEYS.CURRENT_JOB_ID);
      const jobStartTime = sessionStorage.getItem(SESSION_STORAGE_KEYS.JOB_START_TIME);

      if (!existingJobId || !jobStartTime) return;

      const jobAgeMs = Date.now() - new Date(jobStartTime).getTime();
      const MAX_JOB_AGE_MS = API_CONFIG.POLLING_TIMEOUT_MS;

      if (jobAgeMs > MAX_JOB_AGE_MS) {
        sessionStorage.removeItem(SESSION_STORAGE_KEYS.CURRENT_JOB_ID);
        sessionStorage.removeItem(SESSION_STORAGE_KEYS.JOB_START_TIME);
        return;
      }

      const userWantsToResumeJob = window.confirm(
        `You have an ongoing analysis for job ${existingJobId.slice(0, 12)}... from ${Math.floor(jobAgeMs / 1000)} seconds ago.\n\nWould you like to resume checking the status?`
      );

      if (userWantsToResumeJob) {
        navigate(`/processing/${existingJobId}`);
      } else {
        sessionStorage.removeItem(SESSION_STORAGE_KEYS.CURRENT_JOB_ID);
        sessionStorage.removeItem(SESSION_STORAGE_KEYS.JOB_START_TIME);
      }
    };

    checkExistingJob();
  }, [navigate]);

  const handleFileSelect = async (
    file: File,
    context: 'report' | 'prescription' | 'auto'
  ) => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await uploadFile(file, 'en-IN', context);

      sessionStorage.setItem(SESSION_STORAGE_KEYS.CURRENT_JOB_ID, response.job_id);
      sessionStorage.setItem(SESSION_STORAGE_KEYS.JOB_START_TIME, new Date().toISOString());

      navigate(`/processing/${response.job_id}`);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : 'Failed to upload file';
      setError(errorMessage);
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-indigo-50">
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
          <div className="text-center">
            <h1 className="text-4xl sm:text-5xl font-bold bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent mb-2">
              Lumen
            </h1>
            <p className="text-lg text-gray-600">
              Understand your medical reports in simple language
            </p>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-12 sm:px-6 lg:px-8">
        <div className="grid md:grid-cols-2 gap-12 items-center">
          <div className="md:col-span-1">
            <h2 className="text-2xl font-bold text-gray-900 mb-6">
              Upload Your Report
            </h2>
            <FileUploader onFileSelect={handleFileSelect} isLoading={isLoading} />

            {error && (
              <div className="mt-6 p-4 bg-red-50 border border-red-200 rounded-lg flex gap-3">
                <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}
          </div>

          {/* Info Section */}
          <div className="md:col-span-1 space-y-6">
            <div className="bg-white rounded-lg p-6 border border-gray-200">
              <h3 className="text-xl font-semibold text-gray-900 mb-4">
                How It Works
              </h3>
              <ol className="space-y-3 text-gray-700">
                <li className="flex gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-semibold">
                    1
                  </span>
                  <span>
                    <strong>Upload</strong> your medical report or prescription
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-semibold">
                    2
                  </span>
                  <span>
                    <strong>Wait</strong> while we analyze and extract information
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-semibold">
                    3
                  </span>
                  <span>
                    <strong>Get</strong> simple, doctor-approved explanations
                  </span>
                </li>
              </ol>
            </div>

            <div className="bg-white rounded-lg p-6 border border-gray-200">
              <h3 className="text-xl font-semibold text-gray-900 mb-4">
                What We Support
              </h3>
              <ul className="space-y-2 text-gray-700">
                <li className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-blue-600 flex-shrink-0" aria-hidden />
                  <span>Blood test reports</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-blue-600 flex-shrink-0" aria-hidden />
                  <span>Medical prescriptions</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-blue-600 flex-shrink-0" aria-hidden />
                  <span>Diagnostic results</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-blue-600 flex-shrink-0" aria-hidden />
                  <span>Imaging reports</span>
                </li>
              </ul>
            </div>

            <div className="bg-gradient-to-br from-green-50 to-emerald-50 rounded-lg p-6 border border-green-200">
              <h3 className="text-lg font-semibold text-green-900 mb-2 flex items-center gap-2">
                <Info className="w-5 h-5 text-green-900 flex-shrink-0" />
                Pro Tip
              </h3>
              <p className="text-sm text-green-800">
                For best results, upload clear, well-lit photos or high-resolution scans of your
                documents.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-gray-200 mt-12 py-8 px-4">
        <div className="max-w-7xl mx-auto text-center text-sm text-gray-600">
          <p>
            <strong>Disclaimer:</strong> This tool provides general information only and is not a
            substitute for professional medical advice. Always consult with your doctor.
          </p>
        </div>
      </footer>
    </div>
  );
};