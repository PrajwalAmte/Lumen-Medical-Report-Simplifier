import React from 'react';
import {
  Target,
  ArrowRight,
  HelpCircle,
  Utensils,
  Dumbbell,
  BarChart3,
} from 'lucide-react';
import type { ResultResponse } from '../types';

interface Props {
  result: ResultResponse;
}

export const NextStepsTab: React.FC<Props> = ({ result }) => (
  <div className="space-y-6">
    {/* Lifestyle Action Plan */}
    {result.lifestyle_action_plan && (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <Target className="w-5 h-5 text-blue-600" /> Lifestyle Action Plan
        </h3>
        <div className="grid md:grid-cols-2 gap-4">
          {result.lifestyle_action_plan.diet && result.lifestyle_action_plan.diet.length > 0 && (
            <div className="bg-green-50 rounded-lg p-4">
              <h4 className="font-semibold text-green-900 mb-2 flex items-center gap-2">
                <Utensils className="w-4 h-4" /> Diet
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
                <Dumbbell className="w-4 h-4" /> Exercise
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
                <Target className="w-4 h-4" /> Habits
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
                <BarChart3 className="w-4 h-4" /> Monitoring
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
        <ArrowRight className="w-5 h-5 text-blue-600" /> Next Steps
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
          <HelpCircle className="w-5 h-5 text-purple-600" /> Questions to Ask Your Doctor
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
);
