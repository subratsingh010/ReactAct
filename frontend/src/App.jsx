import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import ErrorBoundary from './components/ErrorBoundary'
import NavBar from './components/NavBar'
import { useAuth } from './contexts/useAuth'

const HomePage = lazy(() => import('./pages/HomePage'))
const LoginPage = lazy(() => import('./pages/LoginPage'))
const ProfilePage = lazy(() => import('./pages/ProfilePage'))
const TemplatesPage = lazy(() => import('./pages/TemplatesPage'))
const RegisterPage = lazy(() => import('./pages/RegisterPage'))
const CompanyPage = lazy(() => import('./pages/CompanyPage'))
const TrackingPage = lazy(() => import('./pages/TrackingPage'))
const TrackingDetailPage = lazy(() => import('./pages/TrackingDetailPage'))
const TrackingMailTestPage = lazy(() => import('./pages/TrackingMailTestPage'))
const TrackingSchedulePage = lazy(() => import('./pages/TrackingSchedulePage'))
const JobsPage = lazy(() => import('./pages/JobsPage'))
const ResumeBuilderPage = lazy(() => import('./pages/ResumeBuilderPage'))
const ResumePreviewPage = lazy(() => import('./pages/ResumePreviewPage'))
const BulkUploadPage = lazy(() => import('./pages/BulkUploadPage'))

function RequireAuth({ children }) {
  const { isLoggedIn } = useAuth()
  const location = useLocation()

  if (!isLoggedIn) {
    const redirectPath = `${location.pathname || '/'}${location.search || ''}${location.hash || ''}`
    sessionStorage.setItem('redirectAfterLogin', redirectPath)
    return <Navigate to="/login" replace />
  }

  return children
}

function PublicOnly({ children }) {
  const { isLoggedIn } = useAuth()

  if (!isLoggedIn) return children

  const redirect = sessionStorage.getItem('redirectAfterLogin') || '/'
  const safeRedirect = redirect.startsWith('/') ? redirect : '/'
  sessionStorage.removeItem('redirectAfterLogin')
  return <Navigate to={safeRedirect} replace />
}

function AppLayout() {
  const { isLoggedIn } = useAuth()
  const location = useLocation()
  const showNav = isLoggedIn && location.pathname !== '/login' && location.pathname !== '/register'

  return (
    <div className="app-shell min-h-screen">
      <ErrorBoundary>
        {showNav && <NavBar />}
        <div className="app-content mx-auto w-full">
          <Suspense fallback={<div className="page page-wide mx-auto w-full"><p className="hint">Loading...</p></div>}>
            <Routes>
              <Route path="/login" element={<PublicOnly><LoginPage /></PublicOnly>} />
              <Route path="/register" element={<PublicOnly><RegisterPage /></PublicOnly>} />
              <Route path="/" element={<RequireAuth><HomePage /></RequireAuth>} />
              <Route path="/profile" element={<RequireAuth><ProfilePage /></RequireAuth>} />
              <Route path="/templates" element={<RequireAuth><TemplatesPage /></RequireAuth>} />
              <Route path="/companies" element={<RequireAuth><CompanyPage /></RequireAuth>} />
              <Route path="/tracking" element={<RequireAuth><TrackingPage /></RequireAuth>} />
              <Route path="/tracking-schedule" element={<RequireAuth><TrackingSchedulePage /></RequireAuth>} />
              <Route path="/tracking/:trackingId" element={<RequireAuth><TrackingDetailPage /></RequireAuth>} />
              <Route path="/tracking/:trackingId/test-mail" element={<RequireAuth><TrackingMailTestPage /></RequireAuth>} />
              <Route path="/jobs" element={<RequireAuth><JobsPage /></RequireAuth>} />
              <Route path="/bulk-upload" element={<RequireAuth><BulkUploadPage /></RequireAuth>} />
              <Route
                path="/builder"
                element={(
                  <RequireAuth>
                    <ResumeBuilderPage
                      showJdBox
                      enableTailorFlow
                      referenceBuilderSessionKey="tailoredBuilderReferenceBuilder"
                      referenceResumeIdSessionKey="tailoredBuilderReferenceResumeId"
                      aiModelSessionKey="tailoredBuilderAiModel"
                      tailorModeSessionKey="tailoredBuilderTailorMode"
                    />
                  </RequireAuth>
                )}
              />
              <Route path="/tailored-builder" element={<Navigate to="/builder" replace />} />
              <Route path="/preview/:resumeId" element={<RequireAuth><ResumePreviewPage /></RequireAuth>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </div>
      </ErrorBoundary>
    </div>
  )
}

function App() {
  return <AppLayout />
}

export default App
