import { BrowserRouter as Router, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { ErrorBoundary } from './components/ErrorBoundary';
import { UploadPage } from './pages/UploadPage';
import { ProcessingPage } from './pages/ProcessingPage';
import { ResultPage } from './pages/ResultPage';

function ProcessingPageWrapper() {
  const { jobId } = useParams<{ jobId: string }>();
  if (!jobId) {
    return <Navigate to="/" replace />;
  }
  return <ProcessingPage jobId={jobId} />;
}

function App() {
  return (
    <ErrorBoundary>
      <Router>
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/processing/:jobId" element={<ProcessingPageWrapper />} />
          <Route path="/result/:jobId" element={<ResultPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </ErrorBoundary>
  );
}

export default App;
