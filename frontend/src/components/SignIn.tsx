import { loginUrl } from '../api'
import styles from './SignIn.module.css'
import { Orb } from './Orb'

/** Phase 9c: the door, when sign-in is on. */
export function SignIn({ error }: { error?: string | null }) {
  return (
    <div className={styles.screen}>
      <header className={styles.header}>
        <span className={styles.brand}><Orb size={14} />Voltage</span>
      </header>
      <main className={styles.main}>
      <div className={styles.hero}>
        <h1 className={styles.title}>Change what's said in a video you've already shot.</h1>
        <p className={styles.tagline}>
          Sign in to keep your projects, your spend and the voices you make to yourself.
        </p>
        <div className={styles.card}>
          <a className={styles.google} href={loginUrl}>
            <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
              <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.6 2.5 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.3l7.8 6C12.3 13.6 17.7 9.5 24 9.5z" />
              <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4 7.1-10 7.1-17.5z" />
              <path fill="#FBBC05" d="M10.4 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.8-4.7l-7.8-6A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.7l7.8-6z" />
              <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.9 2.3-8.4 2.3-6.3 0-11.7-4.1-13.6-9.9l-7.8 6C6.5 42.6 14.6 48 24 48z" />
            </svg>
            Sign in with Google
          </a>
          <p className={styles.hint}>Nothing is uploaded until you are in. Your account is used only to tell your projects apart.</p>
          {error && <div className={styles.error} role="alert">{error}</div>}
        </div>
      </div>
      </main>
    </div>
  )
}
