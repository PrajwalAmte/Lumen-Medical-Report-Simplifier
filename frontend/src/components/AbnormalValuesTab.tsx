import React, { useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Info,
  Search,
  Heart,
  Utensils,
  HelpCircle,
} from 'lucide-react';
import type { AbnormalValue } from '../types';

interface Props {
  values: AbnormalValue[];
}

const getSeverityClasses = (severity: string) => {
  const map: Record<string, { border: string; bg: string; text: string; value: string }> = {
    critical: {
      border: 'border-red-500',
      bg: 'bg-red-100 text-red-800',
      text: 'text-red-800',
      value: 'text-red-700',
    },
    severe: {
      border: 'border-red-500',
      bg: 'bg-red-100 text-red-800',
      text: 'text-red-800',
      value: 'text-red-700',
    },
    moderate: {
      border: 'border-orange-500',
      bg: 'bg-orange-100 text-orange-800',
      text: 'text-orange-800',
      value: 'text-orange-700',
    },
    mild: {
      border: 'border-yellow-500',
      bg: 'bg-yellow-100 text-yellow-800',
      text: 'text-yellow-800',
      value: 'text-yellow-700',
    },
  };
  return map[severity] || {
    border: 'border-gray-500',
    bg: 'bg-gray-100 text-gray-800',
    text: 'text-gray-800',
    value: 'text-gray-700',
  };
};

export const AbnormalValuesTab: React.FC<Props> = ({ values }) => {
  const [expandedName, setExpandedName] = useState<string | null>(null);

  if (!values || values.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 text-gray-600">
        No abnormal values detected
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {values.map((value, idx) => {
        const isExpanded = expandedName === value.test_name;
        const sc = getSeverityClasses(value.severity);

        return (
          <div key={idx} className={`bg-white rounded-lg shadow-sm border-l-4 ${sc.border} overflow-hidden`}>
            <button
              onClick={() => setExpandedName(isExpanded ? null : value.test_name)}
              className="w-full p-6 text-left hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="text-lg font-bold text-gray-900">{value.test_name}</h3>
                    <span className={`px-2 py-1 ${sc.bg} text-xs font-medium rounded uppercase`}>
                      {value.severity}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-sm">
                    <div>
                      <span className="text-gray-600">Your Value: </span>
                      <span className={`font-bold ${sc.value}`}>{value.value}</span>
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
                    <Info className="w-4 h-4" /> What This Means
                  </h4>
                  <p className="text-gray-700">{value.what_it_means}</p>
                </div>

                {value.common_causes && value.common_causes.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
                      <Search className="w-4 h-4" /> Common Causes
                    </h4>
                    <ul className="space-y-1">
                      {value.common_causes.map((cause, i) => (
                        <li key={i} className="flex items-start gap-2 text-gray-700 text-sm">
                          <span className="text-gray-400 mt-1">•</span>
                          <span>{cause}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="grid md:grid-cols-2 gap-4">
                  {value.lifestyle_recommendations && value.lifestyle_recommendations.length > 0 && (
                    <div className="bg-blue-50 rounded-lg p-4">
                      <h4 className="text-sm font-semibold text-blue-900 mb-2 flex items-center gap-2">
                        <Heart className="w-4 h-4" /> Lifestyle Changes
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
                        <Utensils className="w-4 h-4" /> Dietary Changes
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
                      <HelpCircle className="w-4 h-4" /> Questions for Your Doctor
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
      })}
    </div>
  );
};
