import React from 'react';
import { AlertCircle, CheckCircle, Pill } from 'lucide-react';

interface ResultCardProps {
  children: React.ReactNode;
  type?: 'default' | 'abnormal' | 'normal' | 'medicine' | 'summary';
  className?: string;
}

export const ResultCard: React.FC<ResultCardProps> = ({
  children,
  type = 'default',
  className = '',
}) => {
  const baseStyles =
    'p-4 rounded-lg border-l-4 transition-shadow hover:shadow-md';

  const typeStyles: Record<string, string> = {
    default: 'bg-white border-gray-300 border-l-gray-400',
    abnormal:
      'bg-red-50 border-red-300 border-l-red-600 hover:shadow-red-100',
    normal: 'bg-green-50 border-green-300 border-l-green-600 hover:shadow-green-100',
    medicine: 'bg-blue-50 border-blue-300 border-l-blue-600 hover:shadow-blue-100',
    summary: 'bg-gradient-to-br from-purple-50 to-blue-50 border-purple-300 border-l-purple-600',
  };

  return (
    <div className={`${baseStyles} ${typeStyles[type]} ${className}`}>
      {children}
    </div>
  );
};

interface SectionProps {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export const Section: React.FC<SectionProps> = ({
  title,
  icon,
  children,
  className = '',
}) => {
  return (
    <section className={`mb-8 ${className}`}>
      <div className="flex items-center gap-2 mb-4">
        {icon && <div className="text-xl">{icon}</div>}
        <h2 className="text-2xl font-bold text-gray-900">{title}</h2>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
};

interface TestValueRowProps {
  testName: string;
  value: string;
  normalRange: string;
  severity?: 'low' | 'high' | 'critical';
}

export const TestValueRow: React.FC<TestValueRowProps> = ({
  testName,
  value,
  normalRange,
  severity,
}) => {
  const severityColor: Record<string, string> = {
    low: 'text-orange-600 font-medium',
    high: 'text-red-600 font-medium',
    critical: 'text-red-700 font-bold',
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
      <div>
        <p className="text-sm text-gray-600">Test</p>
        <p className="font-semibold text-gray-900">{testName}</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-sm text-gray-600">Value</p>
          <p className={`font-semibold ${severity ? severityColor[severity] : 'text-gray-900'}`}>
            {value}
          </p>
        </div>
        <div>
          <p className="text-sm text-gray-600">Normal</p>
          <p className="font-semibold text-gray-900">{normalRange}</p>
        </div>
      </div>
    </div>
  );
};

interface ConfidenceScoreProps {
  score: number;
}

export const ConfidenceScore: React.FC<ConfidenceScoreProps> = ({ score }) => {
  const percentage = Math.round(score * 100);
  const color =
    percentage >= 80 ? 'bg-green-500' : percentage >= 60 ? 'bg-yellow-500' : 'bg-orange-500';

  return (
    <div className="mb-4">
      <div className="flex justify-between items-center mb-2">
        <p className="text-sm font-medium text-gray-700">Confidence Score</p>
        <span className="text-sm font-semibold text-gray-900">{percentage}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className={`${color} h-2 rounded-full transition-all duration-300`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
};
