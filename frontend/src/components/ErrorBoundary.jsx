import React from 'react'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      const showDetails = Boolean(import.meta.env?.DEV)
      return (
        <div className="page">
          <h1>Page crashed</h1>
          <p className="subtitle">
            Something went wrong while rendering this page.
            {showDetails ? ' Open DevTools console for full details.' : ' Refresh the page or try again.'}
          </p>
          {showDetails ? <pre className="error-box">{String(this.state.error?.stack || this.state.error)}</pre> : null}
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
