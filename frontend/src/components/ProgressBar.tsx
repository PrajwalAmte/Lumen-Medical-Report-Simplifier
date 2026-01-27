import React from 'react';

interface ProgressBarProps {
  progress: number;
  stage: string;
}

const stageLabels: Record<string, string> = {
  extracting_text: 'Extracting Text',
  parsing_content: 'Parsing Content',
  generating_summary: 'Generating Summary',
  analyzing_values: 'Analyzing Values',
  formatting_output: 'Formatting Output',
  completed: 'Completed',
};

export const ProgressBar: React.FC<ProgressBarProps> = ({ progress, stage }) => {
  const displayStage = stageLabels[stage] || stage.replace(/_/g, ' ');

  return (
    <div className="w-full max-w-md mx-auto">
      <div className="mb-4">
        <div className="flex justify-between items-center mb-2">
          <p className="text-sm font-medium text-gray-700">
            {displayStage}
          </p>
          <span className="text-sm font-semibold text-blue-600">
            {progress}%
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2.5">
          <div
            className="bg-blue-600 h-2.5 rounded-full transition-all duration-300 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Animated dots */}
      <div className="flex justify-center items-center gap-1">
        <div className="w-2 h-2 bg-blue-600 rounded-full animate-pulse" />
        <div
          className="w-2 h-2 bg-blue-600 rounded-full animate-pulse"
          style={{ animationDelay: '0.2s' }}
        />
        <div
          className="w-2 h-2 bg-blue-600 rounded-full animate-pulse"
          style={{ animationDelay: '0.4s' }}
        />
      </div>
    </div>
  );
};
