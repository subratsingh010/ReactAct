import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import ProfilePage from './pages/ProfilePage'
import RegisterPage from './pages/RegisterPage'
import CompanyPage from './pages/CompanyPage'
import TrackingPage from './pages/TrackingPage'
import TrackingDetailPage from './pages/TrackingDetailPage'
import JobsPage from './pages/JobsPage'
import ResumeBuilderPage from './pages/ResumeBuilderPage'
import ResumePreviewPage from './pages/ResumePreviewPage'
import ErrorBoundary from './components/ErrorBoundary'
import NavBar from './components/NavBar'
import { useAuth } from './contexts/useAuth'

function RequireAuth({ children }) {
  const { isLoggedIn } = useAuth()
  const location = useLocation()

  if (!isLoggedIn) {
    sessionStorage.setItem('redirectAfterLogin', location.pathname || '/')
    return <Navigate to="/login" replace />
  }

  return children
}

function PublicOnly({ children }) {
  const { isLoggedIn } = useAuth()

  if (!isLoggedIn) return children

  const redirect = sessionStorage.getItem('redirectAfterLogin') || '/'
  sessionStorage.removeItem('redirectAfterLogin')
  return <Navigate to={redirect} replace />
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
          <Routes>
            <Route path="/login" element={<PublicOnly><LoginPage /></PublicOnly>} />
            <Route path="/register" element={<PublicOnly><RegisterPage /></PublicOnly>} />
            <Route path="/" element={<RequireAuth><HomePage /></RequireAuth>} />
            <Route path="/profile" element={<RequireAuth><ProfilePage /></RequireAuth>} />
            <Route path="/companies" element={<RequireAuth><CompanyPage /></RequireAuth>} />
            <Route path="/tracking" element={<RequireAuth><TrackingPage /></RequireAuth>} />
            <Route path="/tracking/:trackingId" element={<RequireAuth><TrackingDetailPage /></RequireAuth>} />
            <Route path="/jobs" element={<RequireAuth><JobsPage /></RequireAuth>} />
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
        </div>
      </ErrorBoundary>
    </div>
  )
}

function App() {
  return <AppLayout />
}

export default App
