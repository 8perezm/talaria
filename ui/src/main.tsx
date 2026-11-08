import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import './index.css'
import App from './App'
import { applyBootTheme } from './lib/theme'

// Apply the last-known Config -> Theme before the first render. Without this
// the dashboard paints one frame in the stock font/colors and visibly swaps
// once /api/config/form answers (ThemeApplier reconciles it right after).
applyBootTheme()

createRoot(document.getElementById('root')!).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>,
)
