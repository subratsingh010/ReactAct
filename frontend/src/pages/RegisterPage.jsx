import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { signupUser } from '../api'

function RegisterPage() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSuccess('')
    const normalizedUsername = username.trim()
    const normalizedEmail = email.trim()

    if (!normalizedUsername || !normalizedEmail || !password || !confirmPassword) {
      setError('All fields are required.')
      return
    }

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      setError('Enter a valid email address.')
      return
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }

    try {
      setLoading(true)
      await signupUser(normalizedUsername, normalizedEmail, password)
      setSuccess('Account created. Redirecting to login...')
      setTimeout(() => navigate('/login'), 1200)
    } catch (err) {
      setError(err.message || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="page mx-auto w-full max-w-2xl">
      <h1>Register</h1>
      <form className="form" onSubmit={handleSubmit}>
        <label htmlFor="register-username">
          Username
          <input
            id="register-username"
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="Choose username"
          />
        </label>

        <label htmlFor="register-email">
          Email
          <input
            id="register-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
          />
        </label>

        <label htmlFor="register-password">
          Password
          <input
            id="register-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Create password"
          />
        </label>

        <label htmlFor="register-confirm-password">
          Confirm Password
          <input
            id="register-confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            placeholder="Confirm password"
          />
        </label>

        {error && <p className="error">{error}</p>}
        {success && <p className="success">{success}</p>}

        <div className="actions">
          <button type="submit" disabled={loading}>
            {loading ? 'Creating account...' : 'Register'}
          </button>
          <button type="button" className="secondary" onClick={() => navigate('/login')}>
            Go to Login
          </button>
        </div>
      </form>
    </main>
  )
}

export default RegisterPage
