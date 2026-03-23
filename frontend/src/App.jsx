import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import DashboardPage from './pages/DashboardPage'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
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

  const redirect = sessionStorage.getItem('redirectAfterLogin') || '/dashboard'
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
            <Route path="/dashboard" element={<RequireAuth><DashboardPage /></RequireAuth>} />
            <Route path="/builder" element={<RequireAuth><ResumeBuilderPage /></RequireAuth>} />
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
