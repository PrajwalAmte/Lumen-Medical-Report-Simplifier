import { useEffect, useState, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  CheckCircle,
  Pill,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  FileText,
  Calendar,
  Building2,
  Globe,
  Activity,
  Clock,
  HelpCircle,
  ArrowRight,
  Download,
  Upload,
  Search,
  Heart,
  Utensils,
  Dumbbell,
  Target,
  BarChart3,
  Zap,
  Info,
  Shield
} from 'lucide-react';
import {
  ResultCard,
  Section,
  TestValueRow,
  ConfidenceScore,
} from '../components/index';
import { getResult } from '../api/lumenApi';
import { API_CONFIG } from '../config/constants';
import type { ResultResponse, AbnormalValue, NormalValue, Medicine, PatternAnalysis, LifestyleActionPlan } from '../types';

export const ResultPage: React.FC = () => {
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const [result, setResult] = useState<ResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedAbnormal, setExpandedAbnormal] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>('overview');
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
        retryCount = 0;

        sessionStorage.removeItem(API_CONFIG.STORAGE_KEYS.CURRENT_JOB_ID);
        sessionStorage.removeItem(API_CONFIG.STORAGE_KEYS.JOB_START_TIME);
      } catch (err) {
        if (!isMountedRef.current) return;

        retryCount += 1;

        if (retryCount <= 3) {
          setTimeout(() => {
            if (isMountedRef.current) {
              fetchResult();
            }
          }, 1000 * retryCount);
        } else {
          const errorMsg = err instanceof Error ? err.message : 'Failed to fetch results';
          setError(errorMsg);
        }
      } finally {
        if (isMountedRef.current) {
          setLoading(false);
        }
      }
    };

    fetchResult();

    return () => {
      isMountedRef.current = false;
    };
  }, [jobId, navigate]);

  const getSeverityColor = (severity: string) => {
    const colors: Record<string, string> = {
      critical: 'red',
      severe: 'red',
      moderate: 'orange',
      mild: 'yellow'
    };
    return colors[severity] || 'gray';
  };

  const getUrgencyConfig = (level: string) => {
    const configs: Record<string, { color: string; icon: any; text: string }> = {
      emergency: { color: 'red', icon: AlertCircle, text: 'Seek immediate medical attention' },
      urgent: { color: 'orange', icon: AlertTriangle, text: 'Schedule urgent appointment with your doctor' },
      soon: { color: 'yellow', icon: Clock, text: 'Schedule appointment within 1-2 weeks' },
      routine: { color: 'green', icon: CheckCircle, text: 'Routine follow-up as advised' }
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
              <p className="text-sm text-red-700 mt-1">
                {error || 'Unable to load results. Please try again.'}
              </p>
            </div>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => {
                setLoading(true);
                setError(null);
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
                  const resultText = JSON.stringify(result, null, 2);
                  const blob = new Blob([resultText], { type: 'application/json' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `lumen-result-${result.job_id}.json`;
                  a.click();
                }}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
                aria-label="download-result"
              >
                <Download className="w-4 h-4" />
                Download
              </button>
              <button
                onClick={() => navigate('/')}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700"
                aria-label="new-upload"
              >
                <Upload className="w-4 h-4" />
                New Upload
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
        {/* Navigation Tabs */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 mb-6">
          <div className="flex border-b border-gray-200 overflow-x-auto">
            {[
              { id: 'overview', label: 'Overview', icon: Activity, badge: 0 },
              { id: 'abnormal', label: 'Abnormal Values', icon: AlertTriangle, badge: result.abnormal_values?.length || 0 },
              { id: 'normal', label: 'Normal Values', icon: CheckCircle, badge: result.normal_values?.length || 0 },
              { id: 'medicines', label: 'Medicines', icon: Pill, badge: result.medicines?.length || 0 },
              { id: 'actions', label: 'Action Plan', icon: Target, badge: 0 }
            ].map(tab => {
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
            {/* Overview Tab */}
            {activeTab === 'overview' && (
              <>
                {/* Summary Card */}
                <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                  <div className="flex items-start gap-3 mb-4">
                    <Activity className="w-6 h-6 text-blue-600 flex-shrink-0" />
                    <div className="flex-1">
                      <h2 className="text-xl font-bold text-gray-900 mb-2">Overall Summary</h2>
                      <p className="text-gray-700 leading-relaxed">{result.overall_summary || 'No data available'}</p>
                    </div>
                  </div>
                  
                  {/* Confidence Score */}
                  <div className="mt-4 pt-4 border-t border-gray-200">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-gray-700">Analysis Confidence</span>
                      <span className="text-sm font-bold text-gray-900">{(result.confidence_score * 100).toFixed(0)}%</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div 
                        className="bg-blue-600 h-2 rounded-full transition-all"
                        style={{ width: `${result.confidence_score * 100}%` }}
                      />
                    </div>
                  </div>
                </div>

                {/* Report Details */}
                {result.input_summary && (
                  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                    <h3 className="text-lg font-bold text-gray-900 mb-4">Report Details</h3>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="flex items-start gap-3">
                        <FileText className="w-5 h-5 text-gray-400 flex-shrink-0 mt-0.5" />
                        <div>
                          <p className="text-sm text-gray-600">Document Type</p>
                          <p className="font-medium text-gray-900">{result.input_summary.document_type || 'Unknown'}</p>
                        </div>
                      </div>
                      {result.input_summary.date_of_report && (
                        <div className="flex items-start gap-3">
                          <Calendar className="w-5 h-5 text-gray-400 flex-shrink-0 mt-0.5" />
                          <div>
                            <p className="text-sm text-gray-600">Report Date</p>
                            <p className="font-medium text-gray-900">{result.input_summary.date_of_report}</p>
                          </div>
                        </div>
                      )}
                      {result.input_summary.detected_hospital && (
                        <div className="flex items-start gap-3">
                          <Building2 className="w-5 h-5 text-gray-400 flex-shrink-0 mt-0.5" />
                          <div>
                            <p className="text-sm text-gray-600">Hospital/Lab</p>
                            <p className="font-medium text-gray-900">{result.input_summary.detected_hospital}</p>
                          </div>
                        </div>
                      )}
                      <div className="flex items-start gap-3">
                        <Globe className="w-5 h-5 text-gray-400 flex-shrink-0 mt-0.5" />
                        <div>
                          <p className="text-sm text-gray-600">Language</p>
                          <p className="font-medium text-gray-900">{result.input_summary.detected_language?.toUpperCase() || 'Unknown'}</p>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Pattern Analysis */}
                {result.pattern_analysis && (
                  <div className="bg-indigo-50 rounded-lg border border-indigo-200 p-6">
                    <div className="flex items-start gap-3 mb-4">
                      <Search className="w-5 h-5 text-indigo-600 flex-shrink-0 mt-0.5" />
                      <h3 className="text-lg font-bold text-indigo-900">Pattern Analysis</h3>
                    </div>
                    
                    {result.pattern_analysis.related_abnormalities && (
                      <div className="mb-4">
                        <p className="text-sm font-semibold text-indigo-900 mb-1">Related Findings</p>
                        <p className="text-indigo-800">{result.pattern_analysis.related_abnormalities}</p>
                      </div>
                    )}
                    
                    {result.pattern_analysis.potential_conditions && result.pattern_analysis.potential_conditions.length > 0 && (
                      <div className="mb-4">
                        <p className="text-sm font-semibold text-indigo-900 mb-2">Potential Conditions</p>
                        <div className="flex flex-wrap gap-2">
                          {result.pattern_analysis.potential_conditions.map((condition, i) => (
                            <span key={i} className="px-3 py-1 bg-indigo-100 text-indigo-800 text-sm rounded-full">
                              {condition}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    
                    {result.pattern_analysis.underlying_mechanisms && (
                      <div>
                        <p className="text-sm font-semibold text-indigo-900 mb-1">Underlying Mechanisms</p>
                        <p className="text-sm text-indigo-800">{result.pattern_analysis.underlying_mechanisms}</p>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}

            {/* Abnormal Values Tab */}
            {activeTab === 'abnormal' && (
              <div className="space-y-4">
                {result.abnormal_values && result.abnormal_values.length > 0 ? (
                  result.abnormal_values.map((value: AbnormalValue, idx) => {
                  const isExpanded = expandedAbnormal === value.test_name;
                  const color = getSeverityColor(value.severity);
                  
                  return (
                    <div key={idx} className={`bg-white rounded-lg shadow-sm border-l-4 border-${color}-500 overflow-hidden`}>
                      <button
                        onClick={() => setExpandedAbnormal(isExpanded ? null : value.test_name)}
                        className="w-full p-6 text-left hover:bg-gray-50 transition-colors"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-3 mb-2">
                              <h3 className="text-lg font-bold text-gray-900">{value.test_name}</h3>
                              <span className={`px-2 py-1 bg-${color}-100 text-${color}-800 text-xs font-medium rounded uppercase`}>
                                {value.severity}
                              </span>
                            </div>
                            <div className="flex items-center gap-4 text-sm">
                              <div>
                                <span className="text-gray-600">Your Value: </span>
                                <span className={`font-bold text-${color}-700`}>{value.value}</span>
                              </div>
                              <div>
                                <span className="text-gray-600">Normal Range: </span>
                                <span className="font-medium text-gray-900">{value.normal_range}</span>
                              </div>
                            </div>
                          </div>
                          {isExpanded ? (
                            <ChevronUp className="w-5 h-5 text-gray-400 flex-shrink-0" />
                          ) : (
                            <ChevronDown className="w-5 h-5 text-gray-400 flex-shrink-0" />
                          )}
                        </div>
                      </button>

                      {isExpanded && (
                        <div className="px-6 pb-6 space-y-4 border-t border-gray-200 pt-4">
                          <div>
                            <h4 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
                              <Info className="w-4 h-4" />
                              What This Means
                            </h4>
                            <p className="text-gray-700">{value.what_it_means}</p>
                          </div>

                          {value.common_causes && value.common_causes.length > 0 && (
                            <div>
                              <h4 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
                                <Search className="w-4 h-4" />
                                Common Causes
                              </h4>
                              <ul className="space-y-1">
                                {value.common_causes.map((cause, i) => (
                                  <li key={i} className="flex items-start gap-2 text-gray-700 text-sm">
                                    <span className="text-gray-400 mt-1">•</span>
                                    <span>{cause}</span>
                                  </li>
                                ))}
                              </ul>
                              <div className="flex gap-3 mt-3">
                                <button
                                  onClick={() => {
                                    setLoading(true);
                                    setError(null);
                                  }}
                                  className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
                                  aria-label="retry-fetch-results"
                                >
                                  Retry
                                </button>
                                <button
                                  onClick={() => navigate('/')}
                                  className="flex-1 px-4 py-2 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 transition-colors text-sm font-medium"
                                  aria-label="back-to-upload"
                                >
                                  Back to Upload
                                </button>
                              </div>
                            </div>
                          )}

                          <div className="grid md:grid-cols-2 gap-4">
                            {value.lifestyle_recommendations && value.lifestyle_recommendations.length > 0 && (
                              <div className="bg-blue-50 rounded-lg p-4">
                                <h4 className="text-sm font-semibold text-blue-900 mb-2 flex items-center gap-2">
                                  <Heart className="w-4 h-4" />
                                  Lifestyle Changes
                                </h4>
                                <ul className="space-y-1">
                                  {value.lifestyle_recommendations.map((rec, i) => (
                                    <li key={i} className="flex items-start gap-2 text-blue-800 text-sm">
                                      <span className="text-blue-400 mt-1">•</span>
                                      <span>{rec}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {value.dietary_recommendations && value.dietary_recommendations.length > 0 && (
                              <div className="bg-green-50 rounded-lg p-4">
                                <h4 className="text-sm font-semibold text-green-900 mb-2 flex items-center gap-2">
                                  <Utensils className="w-4 h-4" />
                                  Dietary Changes
                                </h4>
                                <ul className="space-y-1">
                                  {value.dietary_recommendations.map((rec, i) => (
                                    <li key={i} className="flex items-start gap-2 text-green-800 text-sm">
                                      <span className="text-green-400 mt-1">•</span>
                                      <span>{rec}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                          </div>

                          {value.what_to_ask_doctor && value.what_to_ask_doctor.length > 0 && (
                            <div className="bg-purple-50 rounded-lg p-4">
                              <h4 className="text-sm font-semibold text-purple-900 mb-2 flex items-center gap-2">
                                <HelpCircle className="w-4 h-4" />
                                Questions for Your Doctor
                              </h4>
                              <ul className="space-y-1">
                                {value.what_to_ask_doctor.map((q, i) => (
                                  <li key={i} className="flex items-start gap-2 text-purple-800 text-sm">
                                    <span className="text-purple-400 mt-1">•</span>
                                    <span>{q}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                  })
                ) : (
                  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 text-gray-600">No data available</div>
                )}
              </div>
            )}

            {/* Normal Values Tab */}
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
                          {value.what_it_means && (
                            <p className="text-sm text-gray-700">{value.what_it_means}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 text-gray-600">No data available</div>
                )}
              </div>
            )}

            {/* Medicines Tab */}
            {activeTab === 'medicines' && (
              <div className="space-y-4">
                {result.medicines && result.medicines.length > 0 ? (
                  result.medicines.map((medicine: Medicine, idx) => (
                    <div key={idx} className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                    <div className="flex items-start gap-3 mb-4">
                      <Pill className="w-6 h-6 text-blue-600 flex-shrink-0" />
                      <div>
                        <h3 className="text-lg font-bold text-gray-900">{medicine.name}</h3>
                        {medicine.generic_name && (
                          <p className="text-sm text-gray-600">Generic: {medicine.generic_name}</p>
                        )}
                      </div>
                    </div>

                    <div className="space-y-4">
                      <div>
                        <h4 className="text-sm font-semibold text-gray-900 mb-1">Purpose</h4>
                        <p className="text-gray-700 text-sm">{medicine.purpose}</p>
                      </div>

                      {medicine.mechanism && (
                        <div>
                          <h4 className="text-sm font-semibold text-gray-900 mb-1 flex items-center gap-2">
                            <Zap className="w-4 h-4" />
                            How It Works
                          </h4>
                          <p className="text-gray-700 text-sm">{medicine.mechanism}</p>
                        </div>
                      )}

                      <div>
                        <h4 className="text-sm font-semibold text-gray-900 mb-1">How to Take</h4>
                        <p className="text-gray-700 text-sm">{medicine.how_to_take}</p>
                      </div>

                      <div className="grid md:grid-cols-2 gap-4">
                        {medicine.common_side_effects && medicine.common_side_effects.length > 0 && (
                          <div className="bg-yellow-50 rounded-lg p-4">
                            <h4 className="text-sm font-semibold text-yellow-900 mb-2">Common Side Effects</h4>
                            <ul className="space-y-1">
                              {medicine.common_side_effects.map((effect, i) => (
                                <li key={i} className="flex items-start gap-2 text-yellow-800 text-sm">
                                  <span className="text-yellow-400 mt-1">•</span>
                                  <span>{effect}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {medicine.serious_side_effects && medicine.serious_side_effects.length > 0 && (
                          <div className="bg-red-50 rounded-lg p-4">
                            <h4 className="text-sm font-semibold text-red-900 mb-2 flex items-center gap-2">
                              <AlertCircle className="w-4 h-4" />
                              Serious Side Effects
                            </h4>
                            <ul className="space-y-1">
                              {medicine.serious_side_effects.map((effect, i) => (
                                <li key={i} className="flex items-start gap-2 text-red-800 text-sm">
                                  <span className="text-red-400 mt-1">•</span>
                                  <span>{effect}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>

                      {medicine.drug_interactions && medicine.drug_interactions.length > 0 && (
                        <div className="bg-orange-50 rounded-lg p-4">
                          <h4 className="text-sm font-semibold text-orange-900 mb-2 flex items-center gap-2">
                            <AlertTriangle className="w-4 h-4" />
                            Drug Interactions
                          </h4>
                          <ul className="space-y-1">
                            {medicine.drug_interactions.map((interaction, i) => (
                              <li key={i} className="flex items-start gap-2 text-orange-800 text-sm">
                                <span className="text-orange-400 mt-1">•</span>
                                <span>{interaction}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {medicine.precautions && medicine.precautions.length > 0 && (
                        <div>
                          <h4 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
                            <Shield className="w-4 h-4" />
                            Precautions
                          </h4>
                          <ul className="space-y-1">
                            {medicine.precautions.map((precaution, i) => (
                              <li key={i} className="flex items-start gap-2 text-gray-700 text-sm">
                                <span className="text-gray-400 mt-1">•</span>
                                <span>{precaution}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {medicine.lifestyle_tips && medicine.lifestyle_tips.length > 0 && (
                        <div className="bg-blue-50 rounded-lg p-4">
                          <h4 className="text-sm font-semibold text-blue-900 mb-2 flex items-center gap-2">
                            <Heart className="w-4 h-4" />
                            Lifestyle Tips
                          </h4>
                          <ul className="space-y-1">
                            {medicine.lifestyle_tips.map((tip, i) => (
                              <li key={i} className="flex items-start gap-2 text-blue-800 text-sm">
                                <span className="text-blue-400 mt-1">•</span>
                                <span>{tip}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {medicine.generic_alternative && (
                        <div className="bg-green-50 rounded-lg p-4">
                          <h4 className="text-sm font-semibold text-green-900 mb-1">Generic Alternative</h4>
                          <p className="text-sm text-green-800">{medicine.generic_alternative}</p>
                        </div>
                      )}

                      {medicine.cost_saving_tip && (
                        <div className="bg-green-50 rounded-lg p-4">
                          <h4 className="text-sm font-semibold text-green-900 mb-1">Cost Saving Tip</h4>
                          <p className="text-sm text-green-800">{medicine.cost_saving_tip}</p>
                        </div>
                      )}
                    </div>
                  </div>
                  ))
                ) : (
                  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 text-gray-600">No data available</div>
                )}
              </div>
            )}

            {/* Action Plan Tab */}
            {activeTab === 'actions' && (
              <div className="space-y-6">
                {/* Lifestyle Action Plan */}
                {result.lifestyle_action_plan && (
                  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                    <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                      <Target className="w-5 h-5 text-blue-600" />
                      Lifestyle Action Plan
                    </h3>
                    <div className="grid md:grid-cols-2 gap-4">
                      {result.lifestyle_action_plan.diet && result.lifestyle_action_plan.diet.length > 0 && (
                        <div className="bg-green-50 rounded-lg p-4">
                          <h4 className="font-semibold text-green-900 mb-2 flex items-center gap-2">
                            <Utensils className="w-4 h-4" />
                            Diet
                          </h4>
                          <ul className="space-y-1">
                            {result.lifestyle_action_plan.diet.map((item, i) => (
                              <li key={i} className="flex items-start gap-2 text-green-800 text-sm">
                                <span className="text-green-400 mt-1">•</span>
                                <span>{item}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {result.lifestyle_action_plan.exercise && result.lifestyle_action_plan.exercise.length > 0 && (
                        <div className="bg-blue-50 rounded-lg p-4">
                          <h4 className="font-semibold text-blue-900 mb-2 flex items-center gap-2">
                            <Dumbbell className="w-4 h-4" />
                            Exercise
                          </h4>
                          <ul className="space-y-1">
                            {result.lifestyle_action_plan.exercise.map((item, i) => (
                              <li key={i} className="flex items-start gap-2 text-blue-800 text-sm">
                                <span className="text-blue-400 mt-1">•</span>
                                <span>{item}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {result.lifestyle_action_plan.habits && result.lifestyle_action_plan.habits.length > 0 && (
                        <div className="bg-purple-50 rounded-lg p-4">
                          <h4 className="font-semibold text-purple-900 mb-2 flex items-center gap-2">
                            <Target className="w-4 h-4" />
                            Habits
                          </h4>
                          <ul className="space-y-1">
                            {result.lifestyle_action_plan.habits.map((item, i) => (
                              <li key={i} className="flex items-start gap-2 text-purple-800 text-sm">
                                <span className="text-purple-400 mt-1">•</span>
                                <span>{item}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {result.lifestyle_action_plan.monitoring && result.lifestyle_action_plan.monitoring.length > 0 && (
                        <div className="bg-orange-50 rounded-lg p-4">
                          <h4 className="font-semibold text-orange-900 mb-2 flex items-center gap-2">
                            <BarChart3 className="w-4 h-4" />
                            Monitoring
                          </h4>
                          <ul className="space-y-1">
                            {result.lifestyle_action_plan.monitoring.map((item, i) => (
                              <li key={i} className="flex items-start gap-2 text-orange-800 text-sm">
                                <span className="text-orange-400 mt-1">•</span>
                                <span>{item}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Next Steps */}
                <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                  <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                    <ArrowRight className="w-5 h-5 text-blue-600" />
                    Next Steps
                  </h3>
                  {result.next_steps && result.next_steps.length > 0 ? (
                    <ol className="space-y-3">
                      {result.next_steps.map((step, idx) => (
                        <li key={idx} className="flex gap-3">
                          <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-semibold">
                            {idx + 1}
                          </span>
                          <p className="text-gray-700 pt-0.5">{step}</p>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="text-gray-600">No data available</p>
                  )}
                </div>

                {/* Questions to Ask Doctor */}
                {result.questions_to_ask_doctor && result.questions_to_ask_doctor.length > 0 && (
                  <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                    <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                      <HelpCircle className="w-5 h-5 text-purple-600" />
                      Questions to Ask Your Doctor
                    </h3>
                    <div className="space-y-2">
                      {result.questions_to_ask_doctor.map((question, idx) => (
                        <div key={idx} className="flex gap-3 p-3 bg-purple-50 rounded-lg">
                          <HelpCircle className="w-4 h-4 text-purple-600 flex-shrink-0 mt-0.5" />
                          <p className="text-gray-700 text-sm">{question}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
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
                  <AlertCircle className="w-5 h-5" />
                  Red Flags - Seek Immediate Care If:
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