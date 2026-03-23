import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { loginUser } from '../api'
import { useAuth } from '../contexts/useAuth'

function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { login } = useAuth()

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')

    if (!username || !password) {
      setError('Username and password are required.')
      return
    }

    try {
      setLoading(true)
      const data = await loginUser(username, password)
      login(data.access, data.refresh)
      const redirect = sessionStorage.getItem('redirectAfterLogin') || '/dashboard'
      sessionStorage.removeItem('redirectAfterLogin')
      navigate(redirect)
    } catch (err) {
      const message = err.message || 'Login failed'
      if (message.toLowerCase().includes('no active account found')) {
        navigate('/register')
        return
      }
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="page mx-auto w-full max-w-2xl">
      <h1>Login</h1>
      <form className="form grid gap-3" onSubmit={handleSubmit}>
        <label htmlFor="username">Username</label>
        <input
          id="username"
          type="text"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          placeholder="Enter username"
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Enter password"
        />

        {error && <p className="error">{error}</p>}

        <div className="actions flex flex-wrap gap-3">
          <button type="submit" disabled={loading}>
            {loading ? 'Logging in...' : 'Login'}
          </button>
          <button type="button" className="secondary" onClick={() => navigate('/register')}>
            Register
          </button>
          <button type="button" className="secondary" onClick={() => navigate('/')}>
            Back
          </button>
        </div>
      </form>
    </main>
  )
}

export default LoginPage
