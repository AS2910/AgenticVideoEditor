import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/globals.css'
import App from './App.tsx'
import { SharePage } from './pages/SharePage'
import { shareToken } from './lib/exports'

// F6: a share link (`#s/<token>`) opens on its own, with no account and none of the app around it.
const token = shareToken(window.location.hash)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {token ? <SharePage token={token} /> : <App />}
  </StrictMode>,
)
