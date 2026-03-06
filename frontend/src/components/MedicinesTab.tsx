import React from 'react';
import {
  Pill,
  AlertCircle,
  AlertTriangle,
  Zap,
  Shield,
  Heart,
} from 'lucide-react';
import type { Medicine } from '../types';

interface Props {
  medicines: Medicine[];
}

export const MedicinesTab: React.FC<Props> = ({ medicines }) => {
  if (!medicines || medicines.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 text-gray-600">
        No medicines detected
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {medicines.map((medicine, idx) => (
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
                  <Zap className="w-4 h-4" /> How It Works
                </h4>
                <p className="text-gray-700 text-sm">{medicine.mechanism}</p>
              </div>
            )}

            {medicine.how_to_take && (
              <div>
                <h4 className="text-sm font-semibold text-gray-900 mb-1">How to Take</h4>
                <p className="text-gray-700 text-sm">{medicine.how_to_take}</p>
              </div>
            )}

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
                    <AlertCircle className="w-4 h-4" /> Serious Side Effects
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
                  <AlertTriangle className="w-4 h-4" /> Drug Interactions
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
                  <Shield className="w-4 h-4" /> Precautions
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
                  <Heart className="w-4 h-4" /> Lifestyle Tips
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
      ))}
    </div>
  );
};
