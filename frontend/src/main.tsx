import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/globals.css'
import App from './App.tsx'
import { SharePage } from './pages/SharePage'
import { shareToken } from './lib/exports'
import { ErrorBoundary } from './components/ErrorBoundary'
import { installErrorHooks } from './lib/errors'

// F6: a share link (`#s/<token>`) opens on its own, with no account and none of the app around it.
const token = shareToken(window.location.hash)
// G8: errors nothing else caught are reported (golive.g8).
installErrorHooks()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>{token ? <SharePage token={token} /> : <App />}</ErrorBoundary>
  </StrictMode>,
)
