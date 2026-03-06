import React from 'react';
import {
  Activity,
  FileText,
  Calendar,
  Building2,
  Globe,
  Search,
} from 'lucide-react';
import type { ResultResponse } from '../types';

interface Props {
  result: ResultResponse;
}

export const SummaryTab: React.FC<Props> = ({ result }) => (
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
);
