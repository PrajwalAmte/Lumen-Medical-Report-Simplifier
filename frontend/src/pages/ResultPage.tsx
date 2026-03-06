import { useEffect, useState, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  CheckCircle,
  Pill,
  AlertTriangle,
  Activity,
  Clock,
  Download,
  Upload,
  Target,
} from 'lucide-react';
import { AbnormalValuesTab } from '../components/AbnormalValuesTab';
import { MedicinesTab } from '../components/MedicinesTab';
import { SummaryTab } from '../components/SummaryTab';
import { NextStepsTab } from '../components/NextStepsTab';
import { getResult } from '../api/lumenApi';
import { API_CONFIG } from '../config/constants';
import type { ResultResponse, NormalValue } from '../types';

export const ResultPage: React.FC = () => {
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const [result, setResult] = useState<ResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>('overview');
  const [retryTrigger, setRetryTrigger] = useState<number>(0);
  const isMountedRef = useRef<boolean>(true);

  useEffect(() => {
    if (!jobId) {
      navigate('/');
      return;
    }

    isMountedRef.current = true;
    let retryCount = 0;

    const fetchResult = async () => {
      try {
        const data = await getResult(jobId);
        if (!isMountedRef.current) return;

        setResult(data);
        setError(null);
        sessionStorage.removeItem(API_CONFIG.STORAGE_KEYS.CURRENT_JOB_ID);
        sessionStorage.removeItem(API_CONFIG.STORAGE_KEYS.JOB_START_TIME);
      } catch (err) {
        if (!isMountedRef.current) return;
        retryCount += 1;
        if (retryCount <= 3) {
          setTimeout(() => {
            if (isMountedRef.current) fetchResult();
          }, 1000 * retryCount);
        } else {
          setError(err instanceof Error ? err.message : 'Failed to fetch results');
        }
      } finally {
        if (isMountedRef.current) setLoading(false);
      }
    };

    fetchResult();
    return () => { isMountedRef.current = false; };
  }, [jobId, navigate, retryTrigger]);

  const getUrgencyConfig = (level: string) => {
    const configs: Record<string, { color: string; icon: any; text: string }> = {
      emergency: { color: 'red', icon: AlertCircle, text: 'Seek immediate medical attention' },
      urgent: { color: 'orange', icon: AlertTriangle, text: 'Schedule urgent appointment with your doctor' },
      soon: { color: 'yellow', icon: Clock, text: 'Schedule appointment within 1-2 weeks' },
      routine: { color: 'green', icon: CheckCircle, text: 'Routine follow-up as advised' },
    };
    return configs[level] || configs.routine;
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
        <div className="bg-white rounded-lg shadow-lg p-8 text-center">
          <div className="w-8 h-8 border-4 border-gray-300 border-t-blue-600 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-600">Processing report...</p>
        </div>
      </div>
    );
  }

  if (error || !result) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
        <div className="bg-white rounded-lg shadow-lg p-8 max-w-md w-full">
          <div className="flex gap-3 items-start mb-4">
            <AlertCircle className="w-6 h-6 text-red-600 flex-shrink-0 mt-1" />
            <div>
              <h2 className="font-bold text-red-900">Error Loading Results</h2>
              <p className="text-sm text-red-700 mt-1">{error || 'Unable to load results. Please try again.'}</p>
            </div>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => {
                setLoading(true);
                setError(null);
                setRetryTrigger(prev => prev + 1);
              }}
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
            >
              Retry
            </button>
            <button
              onClick={() => navigate('/')}
              className="flex-1 px-4 py-2 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 transition-colors text-sm font-medium"
            >
              Back to Upload
            </button>
          </div>
        </div>
      </div>
    );
  }

  const urgencyConfig = getUrgencyConfig(result.urgency_level || 'routine');
  const UrgencyIcon = urgencyConfig.icon;

  const tabs = [
    { id: 'overview', label: 'Overview', icon: Activity, badge: 0 },
    { id: 'abnormal', label: 'Abnormal Values', icon: AlertTriangle, badge: result.abnormal_values?.length || 0 },
    { id: 'normal', label: 'Normal Values', icon: CheckCircle, badge: result.normal_values?.length || 0 },
    { id: 'medicines', label: 'Medicines', icon: Pill, badge: result.medicines?.length || 0 },
    { id: 'actions', label: 'Action Plan', icon: Target, badge: 0 },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <h1
              className="text-2xl font-bold text-gray-900 cursor-pointer hover:text-blue-600 transition-colors"
              onClick={() => navigate('/')}
            >
              Lumen - Medical Report Analysis
            </h1>
            <div className="flex gap-3">
              <button
                onClick={() => {
                  const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `lumen-result-${result.job_id}.json`;
                  a.click();
                }}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
                aria-label="download-result"
              >
                <Download className="w-4 h-4" /> Download
              </button>
              <button
                onClick={() => navigate('/')}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700"
                aria-label="new-upload"
              >
                <Upload className="w-4 h-4" /> New Upload
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        {/* Navigation Tabs */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 mb-6">
          <div className="flex border-b border-gray-200 overflow-x-auto">
            {tabs.map(tab => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  aria-label={`${tab.label}-tab`}
                  className={`flex items-center gap-2 px-6 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                    activeTab === tab.id
                      ? 'border-blue-600 text-blue-600'
                      : 'border-transparent text-gray-600 hover:text-gray-900'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                  {tab.badge > 0 && (
                    <span className={`px-2 py-0.5 text-xs rounded-full ${
                      activeTab === tab.id ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-700'
                    }`}>
                      {tab.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Content */}
          <div className="lg:col-span-2 space-y-6">
            {activeTab === 'overview' && <SummaryTab result={result} />}
            {activeTab === 'abnormal' && <AbnormalValuesTab values={result.abnormal_values} />}
            {activeTab === 'normal' && (
              <div className="space-y-3">
                {result.normal_values && result.normal_values.length > 0 ? (
                  result.normal_values.map((value: NormalValue, idx) => (
                    <div key={idx} className="bg-white rounded-lg shadow-sm border-l-4 border-green-500 p-4">
                      <div className="flex items-start gap-3">
                        <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                          <h3 className="font-bold text-gray-900 mb-1">{value.test_name}</h3>
                          <div className="flex items-center gap-4 text-sm mb-2">
                            <div>
                              <span className="text-gray-600">Value: </span>
                              <span className="font-medium text-gray-900">{value.value}</span>
                            </div>
                            <div>
                              <span className="text-gray-600">Normal Range: </span>
                              <span className="font-medium text-gray-900">{value.normal_range}</span>
                            </div>
                          </div>
                          {value.what_it_means && <p className="text-sm text-gray-700">{value.what_it_means}</p>}
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 text-gray-600">No data available</div>
                )}
              </div>
            )}
            {activeTab === 'medicines' && <MedicinesTab medicines={result.medicines} />}
            {activeTab === 'actions' && <NextStepsTab result={result} />}
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Urgency Level */}
            {result.urgency_level && (
              <div className={`rounded-lg shadow-sm border-l-4 p-4 ${
                urgencyConfig.color === 'red' ? 'bg-red-50 border-red-600' :
                urgencyConfig.color === 'orange' ? 'bg-orange-50 border-orange-600' :
                urgencyConfig.color === 'yellow' ? 'bg-yellow-50 border-yellow-600' :
                'bg-green-50 border-green-600'
              }`}>
                <div className="flex items-start gap-3">
                  <UrgencyIcon className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
                    urgencyConfig.color === 'red' ? 'text-red-600' :
                    urgencyConfig.color === 'orange' ? 'text-orange-600' :
                    urgencyConfig.color === 'yellow' ? 'text-yellow-600' :
                    'text-green-600'
                  }`} />
                  <div>
                    <h3 className={`font-bold text-sm mb-1 ${
                      urgencyConfig.color === 'red' ? 'text-red-900' :
                      urgencyConfig.color === 'orange' ? 'text-orange-900' :
                      urgencyConfig.color === 'yellow' ? 'text-yellow-900' :
                      'text-green-900'
                    }`}>
                      Urgency: <span className="capitalize">{result.urgency_level}</span>
                    </h3>
                    <p className={`text-sm ${
                      urgencyConfig.color === 'red' ? 'text-red-800' :
                      urgencyConfig.color === 'orange' ? 'text-orange-800' :
                      urgencyConfig.color === 'yellow' ? 'text-yellow-800' :
                      'text-green-800'
                    }`}>
                      {urgencyConfig.text}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Red Flags */}
            {result.red_flags && result.red_flags.length > 0 && (
              <div className="bg-red-50 rounded-lg shadow-sm border-l-4 border-red-600 p-4">
                <h3 className="font-bold text-red-900 mb-3 flex items-center gap-2">
                  <AlertCircle className="w-5 h-5" /> Red Flags - Seek Immediate Care If:
                </h3>
                <ul className="space-y-2">
                  {result.red_flags.map((flag, i) => (
                    <li key={i} className="flex items-start gap-2 text-red-800 text-sm">
                      <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                      <span>{flag}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Processing Metadata */}
            {result.metadata && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
                <h3 className="font-semibold text-gray-900 mb-3 text-sm">Processing Details</h3>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Processing Time</span>
                    <span className="font-medium text-gray-900">{result.metadata.processing_time_sec}s</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">OCR Engine</span>
                    <span className="font-medium text-gray-900">{result.metadata.ocr_engine}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">LLM Provider</span>
                    <span className="font-medium text-gray-900">{result.metadata.llm_provider}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Model</span>
                    <span className="font-medium text-gray-900">{result.metadata.model}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Disclaimer */}
            {result.disclaimer && (
              <div className="bg-yellow-50 rounded-lg shadow-sm border-l-4 border-yellow-600 p-4">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-yellow-600 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-yellow-800">
                    <strong>Important:</strong> {result.disclaimer}
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
