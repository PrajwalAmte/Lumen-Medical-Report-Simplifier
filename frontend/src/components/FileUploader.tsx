import React, { useCallback, useState } from 'react';
import { Cloud, AlertCircle, CheckCircle } from 'lucide-react';
import { API_CONFIG } from '../config/constants';

interface FileUploaderProps {
  onFileSelect: (file: File, context: 'report' | 'prescription' | 'auto') => void;
  isLoading: boolean;
}

export const FileUploader: React.FC<FileUploaderProps> = ({
  onFileSelect,
  isLoading,
}) => {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [context, setContext] = useState<'report' | 'prescription' | 'auto'>(
    'auto'
  );
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const validateFile = (file: File): boolean => {
    const allowedTypes = API_CONFIG.FILE_VALIDATION.ALLOWED_TYPES;
    const maxSizeMb = API_CONFIG.FILE_VALIDATION.MAX_SIZE_MB;
    const maxSizeBytes = maxSizeMb * 1024 * 1024;

    if (!allowedTypes.includes(file.type)) {
      setError('Only PDF, JPG, and PNG files are allowed');
      return false;
    }
    if (file.size > maxSizeBytes) {
      setError(`File size must be less than ${maxSizeMb}MB`);
      return false;
    }
    setError(null);
    setSuccess(`File selected: ${file.name}`);
    return true;
  };

  const handleDrag = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.type === 'dragenter' || e.type === 'dragover') {
        setDragActive(true);
      } else if (e.type === 'dragleave') {
        setDragActive(false);
      }
    },
    []
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);

      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        const file = e.dataTransfer.files[0];
        if (validateFile(file)) {
          setSelectedFile(file);
        }
      }
    },
    []
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files[0]) {
        const file = e.target.files[0];
        if (validateFile(file)) {
          setSelectedFile(file);
        }
      }
    },
    []
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedFile) {
      onFileSelect(selectedFile, context);
    }
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      {/* File Input Area */}
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        className={`relative p-8 border-2 border-dashed rounded-lg transition-colors cursor-pointer ${
          dragActive
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 bg-gray-50 hover:border-gray-400'
        }`}
      >
        <input
          type="file"
          onChange={handleChange}
          accept=".pdf,.jpg,.jpeg,.png"
          aria-label="file-input"
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          disabled={isLoading}
        />

        <div className="flex flex-col items-center justify-center">
          <Cloud className="w-12 h-12 text-gray-400 mb-3" />
          <p className="text-lg font-semibold text-gray-700">
            Drag and drop your file here
          </p>
          <p className="text-sm text-gray-500 mt-1">
            or click to browse (PDF, JPG, PNG • Max 10MB)
          </p>
        </div>
      </div>

      {/* File Status Messages */}
      {error && (
        <div className="mt-3 flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {success && !error && (
        <div className="mt-3 flex items-start gap-2 p-3 bg-green-50 border border-green-200 rounded">
          <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-green-700">{success}</p>
        </div>
      )}

      {/* Context Selector */}
      {selectedFile && (
        <div className="mt-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Document Type
          </label>
          <select
            value={context}
            onChange={(e) =>
              setContext(
                e.target.value as 'report' | 'prescription' | 'auto'
              )
            }
            disabled={isLoading}
            aria-label="document-type-select"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed"
          >
            <option value="auto">Auto-detect</option>
            <option value="report">Medical Report</option>
            <option value="prescription">Prescription</option>
          </select>
        </div>
      )}

      {/* Submit Button */}
      {selectedFile && (
        <button
          onClick={handleSubmit}
          aria-label="analyze-report"
          disabled={isLoading}
          className={`w-full mt-6 py-3 px-4 rounded-lg font-semibold transition-colors ${
            isLoading
              ? 'bg-gray-400 text-white cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
        >
          {isLoading ? 'Uploading...' : 'Analyze Report'}
        </button>
      )}
    </div>
  );
};
