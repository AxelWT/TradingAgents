import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { useThemeStore } from './stores/themeStore'
import './index.css'

const cleanupTheme = useThemeStore.getState().initialize()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)

if (typeof cleanupTheme === 'function') {
  window.addEventListener('beforeunload', cleanupTheme)
}
