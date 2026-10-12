import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { createConversationArtifact, createSession, createShip30Artifact, deleteAccount as deleteAccountRequest, deleteSession, getMe, getProviderStatus, listArtifacts, listMessages, listSessions, login, logout, register, renameSession, sendMessage, updateAppearance, updateProfile } from '../services/chat'
import type { Artifact, AuthUser, ChatSession, Message, ProviderStatus } from '../types/chat'
import { safeExternalUrl } from '../utils/safeUrl'
import { generateSessionTitle, isDefaultSessionTitle } from '../utils/sessionTitle'
import { Markdown } from '../components/Markdown'

function ThemeToggle({ theme, onToggle }: { theme: 'light' | 'dark'; onToggle: () => void }) {
  return <button className="theme-toggle" type="button" onClick={onToggle} aria-label={`Switch to ${theme === 'dark' ? 'White' : 'Black'} mode`} aria-pressed={theme === 'dark'}>
    <span aria-hidden="true">{theme === 'dark' ? '☼' : '◐'}</span>{theme === 'dark' ? 'White mode' : 'Black mode'}
  </button>
}

const pastelPalettes = [
  { id: 'blue', name: 'Pastel Blue', colors: ['#eaf2ff', '#bcd4ff', '#356ae6'] },
  { id: 'lavender', name: 'Pastel Lavender', colors: ['#f0eaff', '#d3c3ff', '#7652bd'] },
  { id: 'mint', name: 'Pastel Mint', colors: ['#e8f6ef', '#b9e3cc', '#34795a'] },
  { id: 'pink', name: 'Pastel Pink', colors: ['#fff0f3', '#ffc9d5', '#a54463'] },
  { id: 'peach', name: 'Pastel Peach', colors: ['#fff1e7', '#ffd1ad', '#a85432'] },
  { id: 'cream', name: 'Pastel Cream', colors: ['#f8f1df', '#e9d9b7', '#705637'] },
] as const
type PaletteId = typeof pastelPalettes[number]['id']
type SettingsSection = 'profile' | 'appearance' | 'security' | 'privacy'

function safeAuthError(reason: unknown, mode: 'login' | 'register'): string {
  const message = reason instanceof Error ? reason.message : ''
  if (message === 'Email or password is incorrect') return message
  if (message.includes('already exists') || message.includes('Try signing in')) return 'An account with this email already exists. Try signing in instead.'
  if (message.startsWith('email:') || message.startsWith('password:') || message.startsWith('display_name:')) return message
  if (message.includes('Cannot reach')) return message
  if (message.includes('could not be verified') || message.includes('Request verification failed')) return 'Your sign-in could not be verified. Check that cookies are enabled, then try again.'
  return mode === 'login' ? 'We could not sign you in. Check your details and try again.' : 'We could not create your account. Check your details and try again.'
}

function historyGroup(date: string): string {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const value = new Date(date)
  const day = new Date(value.getFullYear(), value.getMonth(), value.getDate())
  const diff = Math.floor((today.getTime() - day.getTime()) / 86400000)
  return diff <= 0 ? 'Today' : diff === 1 ? 'Yesterday' : 'Earlier'
}

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'register'>(() => new URLSearchParams(window.location.search).get('auth') === 'register' ? 'register' : 'login')
  const [theme, setTheme] = useState<'light' | 'dark'>(() => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')
  const [palette, setPalette] = useState<PaletteId>(() => pastelPalettes.some(item => item.id === document.documentElement.dataset.palette) ? document.documentElement.dataset.palette as PaletteId : 'pink')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsSection, setSettingsSection] = useState<SettingsSection>('profile')
  const [profileName, setProfileName] = useState('')
  const [settingsNotice, setSettingsNotice] = useState('')
  const [settingsError, setSettingsError] = useState('')
  const [profileBusy, setProfileBusy] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const [deletePassword, setDeletePassword] = useState('')
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authConfirmPassword, setAuthConfirmPassword] = useState('')
  const [showAuthPassword, setShowAuthPassword] = useState(false)
  const [authName, setAuthName] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState('')
  const [authFieldErrors, setAuthFieldErrors] = useState<Record<string, string>>({})
  const [authSubmitted, setAuthSubmitted] = useState(false)
  const [authNotice, setAuthNotice] = useState('')
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [booting, setBooting] = useState(false)
  const [error, setError] = useState('')
  const [retryMessage, setRetryMessage] = useState('')
  const [retryKey, setRetryKey] = useState('')
  const [historySearch, setHistorySearch] = useState('')
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null)
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null)
  const [artifactViewerOpen, setArtifactViewerOpen] = useState(false)
  const [essayForm, setEssayForm] = useState(false)
  const [conversationArtifactForm, setConversationArtifactForm] = useState(false)
  const [essayTopic, setEssayTopic] = useState('')
  const [conversationArtifactRequest, setConversationArtifactRequest] = useState('')
  const [essayAudience, setEssayAudience] = useState('product managers and startup operators')
  const [essayFormat, setEssayFormat] = useState<'markdown' | 'html'>('markdown')
  const [conversationArtifactFormat, setConversationArtifactFormat] = useState<'markdown' | 'html'>('markdown')
  const [generatingArtifact, setGeneratingArtifact] = useState(false)
  const [artifactError, setArtifactError] = useState('')
  const [artifactNotice, setArtifactNotice] = useState('')
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileArtifactOpen, setMobileArtifactOpen] = useState(false)
  const [researchPanelCollapsed, setResearchPanelCollapsed] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)
  const conversationRef = useRef<HTMLDivElement>(null)
  const essayCreationRef = useRef<HTMLFormElement>(null)
  const artifactCreationRef = useRef<HTMLFormElement>(null)
  const composerInputRef = useRef<HTMLTextAreaElement>(null)
  const followLatestRef = useRef(true)
  const initializedForUser = useRef<string | null>(null)
  const authSubmitRef = useRef(false)
  const creatingSessionRef = useRef(false)
  const sendingMessageRef = useRef(false)
  const activeSessionRef = useRef<ChatSession | null>(activeSession)
  const appearanceSaveRef = useRef<Promise<unknown>>(Promise.resolve())
  activeSessionRef.current = activeSession

  useEffect(() => { if (user) setProfileName(user.display_name ?? '') }, [user?.id])
  useEffect(() => {
    if (!user) return
    setTheme(user.appearance_mode); setPalette(user.pastel_palette)
    document.documentElement.dataset.theme = user.appearance_mode
    document.documentElement.dataset.palette = user.pastel_palette
    try { localStorage.setItem('lenny-theme', user.appearance_mode); localStorage.setItem('lenny-palette', user.pastel_palette) } catch { /* Session theme remains applied. */ }
  }, [user?.id])

  function persistAppearance(nextTheme: 'light' | 'dark', nextPalette: PaletteId) {
    if (!user) return
    appearanceSaveRef.current = appearanceSaveRef.current.catch(() => undefined).then(() => updateAppearance(nextTheme, nextPalette)).then(() => {
      if (document.documentElement.dataset.theme === nextTheme && document.documentElement.dataset.palette === nextPalette) setSettingsNotice('Appearance saved to your account.')
    }).catch(() => {
      if (document.documentElement.dataset.theme === nextTheme && document.documentElement.dataset.palette === nextPalette) setSettingsError('Your appearance changed in this browser, but could not be saved to your account.')
    })
  }

  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    document.documentElement.dataset.theme = next
    try { localStorage.setItem('lenny-theme', next) } catch { /* Theme remains active for this page view. */ }
    persistAppearance(next, palette)
  }

  function choosePalette(next: PaletteId) {
    setPalette(next)
    document.documentElement.dataset.palette = next
    try { localStorage.setItem('lenny-palette', next) } catch { /* Keep the selected palette for this view. */ }
    persistAppearance(theme, next)
  }

  function resetAppearance() {
    const nextTheme = 'light'
    setTheme(nextTheme); setPalette('pink')
    document.documentElement.dataset.theme = nextTheme
    document.documentElement.dataset.palette = 'pink'
    try { localStorage.setItem('lenny-theme', nextTheme); localStorage.setItem('lenny-palette', 'pink') } catch { /* Defaults remain active for this view. */ }
    persistAppearance(nextTheme, 'pink')
  }

  function changeAuthMode(mode: 'login' | 'register') {
    setAuthMode(mode)
    setAuthError('')
    setAuthFieldErrors({})
    setAuthSubmitted(false)
    setAuthNotice('')
    setAuthPassword('')
    setAuthConfirmPassword('')
    setShowAuthPassword(false)
    const url = new URL(window.location.href)
    if (mode === 'register') url.searchParams.set('auth', 'register')
    else url.searchParams.delete('auth')
    window.history.pushState({ authMode: mode }, '', `${url.pathname}${url.search}${url.hash}`)
  }

  useEffect(() => {
    const onPopState = () => setAuthMode(new URLSearchParams(window.location.search).get('auth') === 'register' ? 'register' : 'login')
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const refreshSessions = useCallback(async () => {
    const items = await listSessions()
    setSessions(items)
    return items
  }, [])

  const openSession = useCallback(async (session: ChatSession) => {
    setMobileSidebarOpen(false)
    setError('')
    setRetryMessage('')
    setRetryKey('')
    setActiveSession(session)
    followLatestRef.current = true
    setLoadingHistory(true)
    setActiveArtifact(null)
    try { setMessages(await listMessages(session.id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load this conversation.') }
    finally { setLoadingHistory(false) }
  }, [])

  const startSession = useCallback(async () => {
    if (creatingSessionRef.current) return
    creatingSessionRef.current = true
    setMobileSidebarOpen(false)
    setError('')
    setCreatingSession(true)
    try {
      const session = await createSession()
      followLatestRef.current = true
      setSessions(current => [session, ...current])
      setActiveSession(session)
      setMessages([])
      setActiveArtifact(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start a conversation.') }
    finally { creatingSessionRef.current = false; setCreatingSession(false) }
  }, [])

  useEffect(() => {
    let cancelled = false
    void getMe().then(profile => { if (!cancelled) { setUser(profile); setAuthError('') } }).catch(reason => {
      if (cancelled) return
      setUser(null)
      const message = reason instanceof Error ? reason.message : ''
      if (message === 'Your session expired. Sign in again') {
        setAuthNotice('Your previous session has expired. Sign in to continue.')
        void Promise.resolve(logout()).catch(() => undefined)
      } else {
        // A missing cookie is the normal state for a public login/signup page.
        // Only surface unexpected failures; protected workspace requests must
        // never determine whether registration is available.
        setAuthNotice('')
        setAuthError(message === 'Sign in to continue' ? '' : message)
      }
    }).finally(() => { if (!cancelled) setAuthChecked(true) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (!event.persisted) return
      setAuthChecked(false)
      void getMe().then(profile => {
        setUser(profile)
        setAuthError('')
      }).catch(() => {
        initializedForUser.current = null
        void Promise.resolve(logout()).catch(() => undefined)
        setUser(null)
        setSessions([])
        setMessages([])
        setArtifacts([])
        setActiveSession(null)
        setActiveArtifact(null)
      }).finally(() => setAuthChecked(true))
    }
    window.addEventListener('pageshow', onPageShow)
    return () => window.removeEventListener('pageshow', onPageShow)
  }, [])

  useEffect(() => {
    if (!user) return
    if (initializedForUser.current === user.id) return
    initializedForUser.current = user.id
    let cancelled = false
    async function initialize() {
      setBooting(true)
      try {
        // Check the session with the first protected request before starting the
        // next one. If the cookie is stale, avoid generating a second 401.
        const items = await listSessions()
        if (cancelled) return
        const saved = await listArtifacts()
        if (cancelled) return
        setSessions(items)
        setArtifacts(saved)
        if (items.length) await openSession(items[0])
        else await startSession()
      } catch (reason) {
        if (!cancelled) {
          const message = reason instanceof Error ? reason.message : 'Could not connect to the assistant.'
          if (message === 'Your session expired. Sign in again') {
            setUser(null)
            initializedForUser.current = null
            setAuthError('Your session expired. Please sign in again.')
          } else if (message === 'Sign in to continue') {
            // The backend says there is no authenticated session. Return to the
            // public auth form without misreporting an expiry.
            setUser(null)
            initializedForUser.current = null
            setAuthError('')
          } else setError(message)
        }
      }
      finally { if (!cancelled) setBooting(false) }
    }
    void initialize()
    void getProviderStatus().then(setProviderStatus).catch(() => setProviderStatus(null))
    return () => {
      cancelled = true
      if (initializedForUser.current === user.id) initializedForUser.current = null
    }
  }, [user, openSession, startSession])

  useEffect(() => {
    const conversation = conversationRef.current
    if (conversation && followLatestRef.current) conversation.scrollTop = conversation.scrollHeight
  }, [messages, loading, loadingHistory])

  useEffect(() => {
    const textarea = composerInputRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 176)}px`
  }, [draft])

  async function submitAuth(event: FormEvent) {
    event.preventDefault()
    if (authSubmitRef.current) return
    const fieldErrors: Record<string, string> = {}
    if (authMode === 'register') {
      if (!authName.trim()) fieldErrors.name = 'Enter your name.'
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(authEmail.trim())) fieldErrors.email = 'Enter a valid email address.'
      if (authPassword.length < 12) fieldErrors.password = 'Use at least 12 characters.'
      if (authPassword !== authConfirmPassword) fieldErrors.confirmPassword = 'Passwords do not match.'
    } else {
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(authEmail.trim())) fieldErrors.email = 'Enter a valid email address.'
      if (!authPassword) fieldErrors.password = 'Enter your password.'
    }
    setAuthSubmitted(true)
    setAuthFieldErrors(fieldErrors)
    if (Object.keys(fieldErrors).length) return
    authSubmitRef.current = true
    setAuthBusy(true)
    setAuthError('')
    setAuthNotice('')
    try {
      if (authMode === 'register') {
        await register(authEmail, authPassword, authName)
        setAuthPassword('')
        setAuthConfirmPassword('')
        changeAuthMode('login')
        setAuthNotice('Account created successfully. Please sign in.')
        return
      }
      await login(authEmail, authPassword)
      // Only the login response may create a session. Confirm its cookie with
      // /me before opening the user's private workspace.
      const profile = await getMe()
      setUser(profile)
      setAuthPassword('')
      setAuthConfirmPassword('')
    } catch (reason) {
      const message = safeAuthError(reason, authMode)
      if (message === 'Sign in to continue' || message === 'Your session expired. Sign in again') {
        setUser(null)
        setAuthError('Your sign-in could not be verified. Check that cookies are enabled, then try again.')
      } else {
        const fieldMatch = /^(email|password|display_name):\s*(.+)$/i.exec(message)
        if (fieldMatch) {
          const field = fieldMatch[1].toLowerCase() === 'display_name' ? 'name' : fieldMatch[1].toLowerCase()
          setAuthFieldErrors(current => ({ ...current, [field]: fieldMatch[2] }))
        } else setAuthError(message)
      }
    }
    finally { authSubmitRef.current = false; setAuthBusy(false) }
  }

  async function signOut() {
    try { await logout() }
    catch {
      setError('We could not confirm sign out with the server. Your session is still active; please try again.')
      return
    }
    setUser(null)
    initializedForUser.current = null
    setSessions([])
    setMessages([])
    setArtifacts([])
    setActiveSession(null)
    setActiveArtifact(null)
    setDraft('')
    setError('')
    setRetryMessage('')
    setRetryKey('')
    setSettingsOpen(false)
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault()
    if (!profileName.trim() || profileBusy) return
    setProfileBusy(true); setSettingsError(''); setSettingsNotice('')
    try {
      const updated = await updateProfile(profileName.trim())
      setUser(updated); setProfileName(updated.display_name ?? '')
      setSettingsNotice('Your profile was saved.')
    } catch { setSettingsError('We could not save your profile. Please try again.') }
    finally { setProfileBusy(false) }
  }

  async function confirmDeleteAccount() {
    if (deleteConfirmation !== 'DELETE' || !deletePassword || deleteBusy) return
    setDeleteBusy(true); setSettingsError('')
    try {
      await deleteAccountRequest(deleteConfirmation, deletePassword)
      setDeleteDialogOpen(false)
      await signOut()
      setAuthNotice('Your account and its saved workspace data were deleted.')
    } catch (reason) {
      setSettingsError(reason instanceof Error && reason.message === 'Confirmation or password is incorrect'
        ? 'Enter DELETE and your current password correctly.'
        : 'We could not delete your account. Your account is still active; please try again.')
    } finally { setDeleteBusy(false) }
  }

  async function rename(session: ChatSession) {
    const title = window.prompt('Rename conversation', session.title)
    if (!title?.trim()) return
    try {
      const updated = await renameSession(session.id, title.trim())
      setSessions(current => current.map(item => item.id === updated.id ? updated : item))
      setActiveSession(current => current?.id === updated.id ? updated : current)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not rename conversation.') }
  }

  async function remove(session: ChatSession) {
    if (!window.confirm(`Delete “${session.title}” and its messages?`)) return
    try {
      await deleteSession(session.id)
      const remaining = sessions.filter(item => item.id !== session.id)
      setSessions(remaining)
      setArtifacts(current => current.filter(item => item.session_id !== session.id))
      if (activeSession?.id === session.id) {
        setActiveSession(null)
        setMessages([])
        if (remaining.length) await openSession(remaining[0])
        else await startSession()
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not delete conversation.') }
  }

  async function generateEssay(event: FormEvent) {
    event.preventDefault()
    if (!activeSession || !essayTopic.trim() || generatingArtifact) return
    setGeneratingArtifact(true)
    setArtifactError('')
    setArtifactNotice('')
    try {
      const artifact = await createShip30Artifact(activeSession.id, essayTopic, essayAudience, essayFormat)
      setArtifacts(current => [artifact, ...current.filter(item => item.id !== artifact.id)])
      setActiveArtifact(artifact)
      setArtifactViewerOpen(true)
      setArtifactNotice(artifact.word_count < 1150
        ? `Saved a grounded ${artifact.word_count}-word draft with cited sources.`
        : 'Essay generated and saved to this conversation.')
      setMobileArtifactOpen(true)
      setEssayForm(false)
      setEssayTopic('')
    } catch { setArtifactError('The essay could not be completed. Please retry in a moment; your topic is still available.') }
    finally { setGeneratingArtifact(false) }
  }

  async function generateConversationArtifact(event: FormEvent) {
    event.preventDefault()
    if (!activeSession || !conversationArtifactRequest.trim() || generatingArtifact) return
    setGeneratingArtifact(true)
    setArtifactError('')
    setArtifactNotice('')
    try {
      const artifact = await createConversationArtifact(activeSession.id, conversationArtifactRequest, conversationArtifactFormat)
      setArtifacts(current => [artifact, ...current.filter(item => item.id !== artifact.id)])
      setActiveArtifact(artifact)
      setArtifactViewerOpen(true)
      setArtifactNotice('Grounded artifact generated and saved to this conversation.')
      setConversationArtifactForm(false)
      setConversationArtifactRequest('')
      setMobileArtifactOpen(true)
    } catch {
      setArtifactError('The transcript library could not support that artifact yet. Try a more specific request; your conversation is still available.')
    } finally { setGeneratingArtifact(false) }
  }

  function openEssayCreation() {
    setEssayForm(true)
    setConversationArtifactForm(false)
    setArtifactError('')
    setMobileArtifactOpen(false)
  }

  function openArtifactCreation() {
    setConversationArtifactForm(true)
    setEssayForm(false)
    setArtifactError('')
    setMobileArtifactOpen(false)
  }

  useEffect(() => {
    const target = essayForm ? essayCreationRef.current : conversationArtifactForm ? artifactCreationRef.current : null
    if (target && typeof target.scrollIntoView === 'function') target.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [essayForm, conversationArtifactForm])

  function toggleEssayCreation() {
    if (essayForm) setEssayForm(false)
    else openEssayCreation()
  }

  function toggleArtifactCreation() {
    if (conversationArtifactForm) setConversationArtifactForm(false)
    else openArtifactCreation()
  }

  function isolatedDocument(artifact: Artifact): string {
    const policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'none\'; connect-src \'none\'; img-src data:; media-src data:; style-src \'unsafe-inline\'; font-src data:; object-src \'none\'; frame-src \'none\'; form-action \'none\'; base-uri \'none\'>'
    return /<head[\s>]/i.test(artifact.content)
      ? artifact.content.replace(/<head([^>]*)>/i, `<head$1>${policy}`)
      : `<!doctype html><html><head><meta charset="utf-8">${policy}</head><body>${artifact.content}</body></html>`
  }

  async function sendContent(content: string, retry = false) {
    if (!content || !activeSession || sendingMessageRef.current) return
    followLatestRef.current = true
    sendingMessageRef.current = true
    const requestSessionId = activeSession.id
    const currentSession = activeSession
    const clientMessageId = retry && retryKey ? retryKey : crypto.randomUUID()
    if (!retry && isDefaultSessionTitle(currentSession.title)) {
      const generatedTitle = generateSessionTitle(content)
      if (generatedTitle) {
        setActiveSession(current => current?.id === requestSessionId ? { ...current, title: generatedTitle } : current)
        setSessions(current => current.map(item => item.id === requestSessionId ? { ...item, title: generatedTitle } : item))
      }
    }
    setDraft('')
    setError('')
    if (!retry) { setRetryMessage(''); setRetryKey('') }
    setLoading(true)
    const temporary: Message = { id: `pending-${Date.now()}`, session_id: activeSession.id, role: 'user', content, sources: [], grounded: null, created_at: new Date().toISOString() }
    setMessages(current => [...current, temporary])
    try {
      const response = await sendMessage(requestSessionId, content, clientMessageId)
      setMessages(current => current.some(message => message.id === temporary.id)
        ? [...current.filter(message => message.id !== temporary.id), response.user_message, response.assistant_message]
        : current)
      setRetryKey('')
      setActiveSession(current => current?.id === requestSessionId ? response.session : current)
      setSessions(current => [response.session, ...current.filter(item => item.id !== response.session.id)])
    } catch (reason) {
      setMessages(current => current.filter(message => message.id !== temporary.id))
      if (activeSessionRef.current?.id === requestSessionId) {
        setDraft(content)
        setRetryMessage(content)
        setRetryKey(clientMessageId)
        setError('I could not complete that request. Please retry in a moment; your message is still available.')
      }
    } finally { sendingMessageRef.current = false; setLoading(false) }
  }

  async function submit(event: FormEvent) { event.preventDefault(); await sendContent(draft.trim()) }
  function composerKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void sendContent(draft.trim()) }
  }
  const closeMobilePanels = () => { setMobileSidebarOpen(false); setMobileArtifactOpen(false) }
  const filteredSessions = useMemo(() => sessions.filter(item => item.title.toLowerCase().includes(historySearch.toLowerCase().trim())), [sessions, historySearch])
  const groupedSessions = useMemo(() => ['Today', 'Yesterday', 'Earlier'].map(group => ({ group, items: filteredSessions.filter(item => historyGroup(item.updated_at) === group) })).filter(item => item.items.length), [filteredSessions])
  const usedSources = useMemo(() => {
    const latestMessage = messages[messages.length - 1]
    const latestAssistant = latestMessage?.role === 'assistant' ? latestMessage : null
    const seen = new Set<string>()
    return (latestAssistant?.sources ?? []).filter(source => {
      if (seen.has(source.chunk_id)) return false
      seen.add(source.chunk_id)
      return true
    })
  }, [messages])
  const sessionArtifacts = useMemo(() => artifacts.filter(artifact => artifact.session_id === activeSession?.id), [artifacts, activeSession?.id])

  if (!authChecked) return <main className="auth-screen"><div className="auth-card auth-loading"><div className="brand-mark">L</div><p role="status">Checking your workspace…</p></div></main>
  if (!user) return <main className="auth-screen">
    <section className="auth-story" aria-label="About the Lenny Growth Assistant">
      <div className="auth-brand"><span className="brand-mark">L</span><span>THE LENNY GROWTH<br /><small>INTELLIGENT GROWTH WORKSPACE</small></span></div>
      <div className="auth-story-copy"><span className="eyebrow">RESEARCH FOR WHAT’S NEXT</span><h1>Turn growth knowledge into your next clear decision.</h1><p>Explore practical lessons from Lenny’s Podcast and Newsletter, grounded in the source material behind every answer.</p>
        <ul><li><span>01</span><div><strong>Evidence-grounded answers</strong><small>Relevant ideas from the transcript library.</small></div></li><li><span>02</span><div><strong>Source-linked insights</strong><small>Trace recommendations to their origin.</small></div></li><li><span>03</span><div><strong>Essays built from research</strong><small>Turn useful ideas into a polished draft.</small></div></li></ul>
      </div>
      <div className="knowledge-graphic" aria-hidden="true"><svg viewBox="0 0 520 300" role="presentation"><path d="M32 218C112 210 105 118 193 132S294 232 375 141 451 68 492 54"/><path d="M32 257C115 248 143 185 210 190s99 48 164-3 73-94 118-98"/><g><circle cx="32" cy="218" r="7"/><circle cx="193" cy="132" r="7"/><circle cx="375" cy="141" r="7"/><circle cx="492" cy="54" r="7"/><circle cx="210" cy="190" r="5"/><circle cx="374" cy="187" r="5"/></g></svg><span className="graphic-node node-a">activation</span><span className="graphic-node node-b">retention</span><span className="graphic-node node-c">product insight</span></div>
      <small className="auth-footnote">A quieter way to make better product decisions.</small>
    </section>
    <section className="auth-panel"><div className="auth-panel-top"><span className="auth-mobile-brand"><span className="brand-mark">L</span> LENNY GROWTH ASSISTANT</span><ThemeToggle theme={theme} onToggle={toggleTheme} /></div>
    <form className={`auth-card ${authMode === 'register' ? 'auth-card-register' : 'auth-card-login'}`} noValidate onSubmit={submitAuth}>
    <span className="eyebrow">YOUR GROWTH WORKSPACE</span><h2>{authMode === 'login' ? 'Welcome back' : 'Create your account'}</h2>
    <p>{authMode === 'login' ? 'Sign in to continue with your research and conversations.' : 'Create an account to save conversations and grounded research.'}</p>
    <div className="auth-mode-switch" role="tablist" aria-label="Account access">
      <button type="button" role="tab" aria-selected={authMode === 'login'} className={authMode === 'login' ? 'active' : ''} onClick={() => changeAuthMode('login')}>Sign in</button>
      <button type="button" role="tab" aria-selected={authMode === 'register'} className={authMode === 'register' ? 'active' : ''} onClick={() => changeAuthMode('register')}>Create account</button>
    </div>
    {authNotice && <div className="auth-notice" role="status">{authNotice}</div>}
    <div className={authMode === 'register' ? 'auth-fields auth-register-fields' : 'auth-fields'}>
      {authMode === 'register' && <label>Your name<input autoComplete="name" value={authName} onChange={event => { setAuthName(event.target.value); setAuthFieldErrors(current => ({ ...current, name: '' })) }} maxLength={120} aria-invalid={Boolean(authSubmitted && authFieldErrors.name)} aria-describedby={authSubmitted && authFieldErrors.name ? 'auth-name-error' : undefined} />{authSubmitted && authFieldErrors.name && <small id="auth-name-error" className="field-error">{authFieldErrors.name}</small>}</label>}
      <label>Email<input type="email" autoComplete="email" value={authEmail} onChange={event => { setAuthEmail(event.target.value); setAuthError(''); setAuthNotice(''); setAuthFieldErrors(current => ({ ...current, email: '' })) }} maxLength={254} aria-invalid={Boolean(authSubmitted && authFieldErrors.email)} aria-describedby={authSubmitted && authFieldErrors.email ? 'auth-email-error' : undefined} />{authSubmitted && authFieldErrors.email && <small id="auth-email-error" className="field-error">{authFieldErrors.email}</small>}</label>
      <div className="auth-password-group"><label>Password<span className="password-field"><input type={showAuthPassword ? 'text' : 'password'} autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} value={authPassword} onChange={event => { setAuthPassword(event.target.value); setAuthError(''); setAuthFieldErrors(current => ({ ...current, password: '' })) }} maxLength={256} aria-invalid={Boolean(authSubmitted && authFieldErrors.password)} aria-describedby={authMode === 'register' ? (authSubmitted && authFieldErrors.password ? 'auth-password-error' : 'auth-password-hint') : authSubmitted && authFieldErrors.password ? 'auth-password-error' : undefined} /><button type="button" aria-label={showAuthPassword ? 'Hide password' : 'Show password'} onClick={() => { setShowAuthPassword(value => !value); setAuthError('') }}>{showAuthPassword ? 'Hide' : 'Show'}</button></span></label>
        {authMode === 'register' && <><small id="auth-password-hint" className="password-hint">Use at least 12 characters.</small>{authSubmitted && authFieldErrors.password && <small id="auth-password-error" className="field-error">{authFieldErrors.password}</small>}</>}
      </div>
      {authMode === 'register' && <label>Confirm password<span className="password-field"><input type={showAuthPassword ? 'text' : 'password'} autoComplete="new-password" value={authConfirmPassword} onChange={event => { setAuthConfirmPassword(event.target.value); setAuthFieldErrors(current => ({ ...current, confirmPassword: '' })) }} maxLength={256} aria-invalid={Boolean(authSubmitted && authFieldErrors.confirmPassword)} aria-describedby={authSubmitted && authFieldErrors.confirmPassword ? 'auth-confirm-error' : undefined} /></span>{authSubmitted && authFieldErrors.confirmPassword && <small id="auth-confirm-error" className="field-error">{authFieldErrors.confirmPassword}</small>}</label>}
    </div>
    {authError && <div className="error-banner" role="alert">{authError}</div>}
    <button className="auth-submit" disabled={authBusy}>{authBusy ? 'Please wait…' : authMode === 'login' ? 'Sign in' : 'Create account'}</button>
    {authMode === 'login' ? <p className="auth-help">Already created an account? Sign in with its original password. Password recovery is not configured for this workspace; contact its owner if you cannot remember it.</p> : <p className="auth-help">Already have an account? Choose Sign in above. Creating another account with the same email is not supported.</p>}
    </form><p className="auth-panel-footer">Private workspace · Your password is never shared with the assistant</p></section>
  </main>

  const showWelcome = messages.length === 0
  return <main className={`shell ${sidebarCollapsed ? 'sidebar-is-collapsed' : ''} ${researchPanelCollapsed ? 'research-is-collapsed' : ''}`}>
    <aside id="conversation-sidebar" className={`sidebar ${mobileSidebarOpen ? 'mobile-panel-open' : ''} ${sidebarCollapsed ? 'sidebar-is-collapsed' : ''}`} aria-label="Conversation sidebar">
      <div className="brand"><span className="brand-mark">L</span><div><strong>The Lenny Growth</strong><small>ASSISTANT</small></div><button className="sidebar-collapse" aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!sidebarCollapsed} onClick={() => { if (window.matchMedia?.('(max-width: 1050px)').matches) setMobileSidebarOpen(false); else setSidebarCollapsed(value => !value) }}>{sidebarCollapsed ? '›' : '‹'}</button></div>
      <button className="new-chat" disabled={creatingSession} onClick={() => void startSession()}><span aria-hidden="true">+</span> {creatingSession ? 'Starting…' : 'New chat'}</button>
      <label className="history-search"><span aria-hidden="true">⌕</span><input aria-label="Search conversations" placeholder="Search conversations" value={historySearch} onChange={event => setHistorySearch(event.target.value)} /></label>
      <nav className="session-list" aria-label="Conversation history">
        {groupedSessions.map(({ group, items }) => <section className="history-group" key={group}><h2>{group}</h2>{items.map(session => <div key={session.id} className={`session-row ${activeSession?.id === session.id ? 'active' : ''}`}>
          <button className="nav session-nav" onClick={() => void openSession(session)} title={session.title} aria-label={session.title}><span>{session.title}</span></button>
          <details className="session-menu"><summary aria-label={`Actions for ${session.title}`}>···</summary><button onClick={() => void rename(session)}>Rename</button><button onClick={() => void remove(session)}>Delete</button></details>
        </div>)}</section>)}
        {!groupedSessions.length && <p className="history-empty">{historySearch ? 'No matching conversations' : 'Your conversations will appear here.'}</p>}
      </nav>
      <details className="profile-menu"><summary><span className="avatar">{(user.display_name || user.email).slice(0, 1).toUpperCase()}</span><span><strong>{user.display_name || user.email}</strong><small>{user.email}</small></span><b>⌄</b></summary><div className="profile-menu-actions"><button onClick={() => { setSettingsSection('profile'); setSettingsOpen(true); setSettingsError(''); setSettingsNotice('') }}>Account settings</button><button onClick={() => void signOut()}>Log out</button></div></details>
    </aside>

    <section className={`main ${mobileArtifactOpen ? 'mobile-chat-hidden' : ''}`}>
      <header className="topbar"><div className="crumb"><button className="mobile-action" aria-label="Conversations" aria-expanded={mobileSidebarOpen} aria-controls="conversation-sidebar" onClick={() => setMobileSidebarOpen(value => !value)}>☰</button><span>{activeSession?.title ?? 'New chat'}</span></div><div className="header-actions"><button className="mobile-action" aria-expanded={mobileArtifactOpen} aria-controls="artifact-panel" onClick={() => setMobileArtifactOpen(value => !value)}>Artifacts</button><ThemeToggle theme={theme} onToggle={toggleTheme} /><div className={`status ${loading ? 'status-busy' : ''}`} role="status"><i />{loading ? 'Searching the library…' : providerStatus ? `Configured · ${providerStatus.route_label}` : 'Provider configuration unavailable'}</div></div></header>
      {settingsOpen ? <section className="settings-page" aria-labelledby="settings-title"><header className="settings-heading"><button className="settings-back" onClick={() => setSettingsOpen(false)}>← Back to workspace</button><span className="eyebrow">YOUR ACCOUNT</span><h1 id="settings-title">Account settings</h1><p>Manage your profile, appearance, and account security.</p></header><div className="settings-layout"><nav className="settings-nav" aria-label="Account settings sections">{([['profile','Profile'],['appearance','Appearance'],['security','Security'],['privacy','Data & privacy']] as const).map(([key,label]) => <button key={key} className={settingsSection === key ? 'selected' : ''} aria-current={settingsSection === key ? 'page' : undefined} onClick={() => { setSettingsSection(key); setSettingsError(''); setSettingsNotice('') }}>{label}</button>)}</nav><div className="settings-content">{settingsError && <div className="error-banner" role="alert">{settingsError}</div>}{settingsNotice && <div className="success-banner" role="status">{settingsNotice}</div>}
        {settingsSection === 'profile' && <section className="settings-card"><span className="eyebrow">PROFILE</span><h2>Personal information</h2><p>Your account details and the name shown in your workspace.</p><form className="settings-form" onSubmit={saveProfile}><label>Display name<input aria-label="Display name" value={profileName} maxLength={120} required onChange={event => setProfileName(event.target.value)} /></label><label>Email address<input aria-label="Email address" value={user.email} readOnly /></label><label>Member since<input aria-label="Member since" value={user.created_at ? new Date(user.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : 'Date unavailable'} readOnly /></label><button className="settings-primary" disabled={profileBusy || profileName.trim() === (user.display_name ?? '')}>{profileBusy ? 'Saving…' : 'Save profile'}</button></form></section>}
        {settingsSection === 'appearance' && <section className="settings-card"><span className="eyebrow">APPEARANCE</span><h2>Make it yours</h2><p>Choose a clean White or Black workspace, then add a light pastel accent.</p><div className="appearance-modes" role="group" aria-label="Appearance mode"><button aria-pressed={theme === 'light'} className={theme === 'light' ? 'selected' : ''} onClick={() => theme === 'dark' && toggleTheme()}><span className="mode-preview mode-white" />White mode</button><button aria-pressed={theme === 'dark'} className={theme === 'dark' ? 'selected' : ''} onClick={() => theme === 'light' && toggleTheme()}><span className="mode-preview mode-black" />Black mode</button></div><h3>Pastel color</h3><p>Accent colors stay soft; text and headings remain high contrast.</p><div className="palette-grid" role="group" aria-label="Pastel color palette">{pastelPalettes.map(item => <button key={item.id} className={palette === item.id ? 'selected' : ''} aria-pressed={palette === item.id} onClick={() => choosePalette(item.id)}><span className="palette-swatches">{item.colors.map(color => <i key={color} style={{ backgroundColor: color }} />)}</span><span>{item.name}</span><span className="palette-check" aria-hidden="true">{palette === item.id ? '✓' : ''}</span></button>)}</div><div className="palette-preview"><strong>Live preview</strong><span>Clear ideas, grounded in evidence.</span><small>Headings stay dark and readable in either mode.</small></div><button className="settings-secondary" onClick={resetAppearance}>Reset appearance preferences</button></section>}
        {settingsSection === 'security' && <section className="settings-card"><span className="eyebrow">SECURITY</span><h2>Account access</h2><p>Your account uses a protected session cookie. Password changes and recovery are not currently supported.</p><div className="security-action"><div><strong>Log out</strong><span>End this browser session and return to sign in.</span></div><button className="settings-secondary" onClick={() => void signOut()}>Log out</button></div><div className="danger-zone"><h3>Delete account</h3><p>Permanently remove your account, conversations, messages, artifacts, and active sessions. Shared transcript sources are not deleted.</p><button className="settings-danger" onClick={() => { setDeleteConfirmation(''); setDeletePassword(''); setDeleteDialogOpen(true); setSettingsError('') }}>Delete account…</button></div></section>}
        {settingsSection === 'privacy' && <section className="settings-card"><span className="eyebrow">DATA &amp; PRIVACY</span><h2>Your workspace data</h2><p>Your account owns its chat sessions, messages, and saved artifacts. Deleting the account removes those records. Shared transcript and search-index data remains available to the workspace.</p><div className="privacy-summary"><strong>Account</strong><span>{user.email}</span><strong>Saved conversations</strong><span>{sessions.length} in this workspace</span><strong>Saved artifacts</strong><span>{artifacts.length} in this workspace</span></div></section>}
      </div></div></section> : <>
      <div className="conversation" ref={conversationRef} onScroll={event => { const element = event.currentTarget; followLatestRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 140 }} aria-live="polite" aria-busy={loading || loadingHistory}>
        {loadingHistory && <div className="conversation-state">Loading conversation…</div>}
        {!loadingHistory && showWelcome && <div className="welcome"><div className="eyebrow">THE LENNY GROWTH ASSISTANT</div><h1>Better product decisions<br />start with better questions.</h1><p>Explore activation, retention, product strategy, and growth through Lenny’s Podcast and Newsletter.</p><div className="suggestions">{['How can I improve user activation?', 'What drives long-term retention?', 'How should I prioritize product experiments?', 'What are the strongest lessons on product-market fit?'].map(prompt => <button key={prompt} onClick={() => void sendContent(prompt)}><span aria-hidden="true">↗</span>{prompt}</button>)}</div></div>}
        {!loadingHistory && !showWelcome && <div className="message-list">{messages.map(message => <article key={message.id} className={`message ${message.role}`}><div className="message-label">{message.role === 'user' ? 'YOU' : 'LENNY ASSISTANT'}</div>{message.role === 'assistant' ? <Markdown className="message-content markdown-content" content={message.content} /> : <div className="message-content user-content">{message.content}</div>}
          {message.role === 'assistant' && <div className="message-actions"><button onClick={() => void navigator.clipboard?.writeText(message.content)}>Copy response</button></div>}
          {message.role === 'assistant' && message.grounded === false && <div className="evidence-note">The indexed library did not provide enough relevant evidence for this answer.</div>}</article>)}{loading && <div className="thinking" role="status"><i /><i /><i /> Searching retrieved sources and preparing an answer…</div>}</div>}
        {(essayForm || conversationArtifactForm) && <section className="center-creation-form" aria-label={essayForm ? 'Create Essay' : 'Create Artifact'}>{essayForm && <form ref={essayCreationRef} className="essay-form" onSubmit={generateEssay}><div className="center-creation-heading"><strong>Create Essay</strong><button type="button" aria-label="Close essay form" onClick={() => setEssayForm(false)}>×</button></div><label>Essay topic<input autoFocus value={essayTopic} onChange={event => setEssayTopic(event.target.value)} required minLength={3} maxLength={400} placeholder="What should the essay explore?" /></label><label>Audience<input value={essayAudience} onChange={event => setEssayAudience(event.target.value)} maxLength={300} /></label><label>Format<select value={essayFormat} onChange={event => setEssayFormat(event.target.value as 'markdown' | 'html')}><option value="markdown">Markdown</option><option value="html">HTML + CSS</option></select></label>{artifactError && <div className="error-banner artifact-error" role="alert">Essay generation failed: {artifactError}</div>}<button type="submit" disabled={generatingArtifact || !activeSession}>{generatingArtifact ? 'Searching sources and writing…' : artifactError ? 'Retry essay generation' : 'Generate grounded essay'}</button></form>}{conversationArtifactForm && <form ref={artifactCreationRef} className="essay-form" onSubmit={generateConversationArtifact}><div className="center-creation-heading"><strong>Create Artifact</strong><button type="button" aria-label="Close artifact form" onClick={() => setConversationArtifactForm(false)}>×</button></div><label>What should the artifact cover?<input aria-label="Artifact request" autoFocus value={conversationArtifactRequest} onChange={event => setConversationArtifactRequest(event.target.value)} required minLength={3} maxLength={400} placeholder="e.g. Summarize the retention strategy we discussed" /></label><label>Format<select aria-label="Artifact format" value={conversationArtifactFormat} onChange={event => setConversationArtifactFormat(event.target.value as 'markdown' | 'html')}><option value="markdown">Markdown document</option><option value="html">HTML + CSS page</option></select></label>{artifactError && <div className="error-banner artifact-error" role="alert">{artifactError}</div>}<button type="submit" disabled={generatingArtifact || !activeSession || !conversationArtifactRequest.trim()}>{generatingArtifact ? 'Searching sources and creating…' : 'Generate grounded artifact'}</button></form>}</section>}
      </div>
      <div className="composer-wrap"><div className="creation-toolbar" role="group" aria-label="Create from this conversation"><button type="button" onClick={toggleEssayCreation} disabled={!activeSession || generatingArtifact} aria-label="Open Create Essay form">✍️ Create Essay</button><button type="button" onClick={toggleArtifactCreation} disabled={!activeSession || generatingArtifact} aria-label="Open Create Artifact form">📄 Create Artifact</button></div>{error && <div className="error-banner" role="alert">{error}{retryMessage && <button type="button" disabled={loading} onClick={() => void sendContent(retryMessage, true)}>Retry message</button>}</div>}
        <form className="composer" onSubmit={submit}><div className="composer-heading"><span>Ask Lenny a question</span><small>Grounded in the transcript library</small></div><textarea ref={composerInputRef} aria-label="Ask a question" placeholder="Ask about product, growth, or building…" value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={composerKey} disabled={booting || loading || !activeSession} rows={1} /><div className="composer-footer"><span>Enter to send · Shift+Enter for a new line</span><button aria-label="Send message" disabled={!draft.trim() || loading || !activeSession}>↑</button></div></form>
        <div className="fineprint">Answers are grounded in retrieved source material when available.</div>
      </div>
      </>}
    </section>

    <aside id="artifact-panel" className={`artifact ${mobileArtifactOpen ? 'mobile-panel-open' : ''} ${researchPanelCollapsed ? 'research-collapsed' : ''}`} aria-label="Research and artifacts"><div className="artifact-head"><div><span className="eyebrow">CURRENT CONVERSATION</span><h2>Research &amp; Artifacts</h2></div><span className="artifact-saved-count" aria-label={`${sessionArtifacts.length} saved artifacts`}>{sessionArtifacts.length} saved</span><button className="research-collapse" onClick={() => setResearchPanelCollapsed(value => !value)} aria-label={researchPanelCollapsed ? 'Expand research panel' : 'Collapse research panel'} aria-expanded={!researchPanelCollapsed}>{researchPanelCollapsed ? '‹' : '›'}</button><button className="mobile-close" onClick={() => setMobileArtifactOpen(false)} aria-label="Close artifacts">×</button></div>
      {artifactNotice && <div className="artifact-notice" role="status">{artifactNotice}</div>}
      <section className="sources-library" aria-label="Research Results"><div className="artifact-section-heading"><h3>Research Results</h3><span>{usedSources.length}</span></div>{usedSources.length ? <div className="sources-library-list">{usedSources.map(source => { const url = safeExternalUrl(source.url); return <a key={source.chunk_id} href={url} target={url ? '_blank' : undefined} rel={url ? 'noopener noreferrer' : undefined} className="source-library-row"><span>{source.source_id}</span><div><strong>{source.title}</strong><small>{source.document_type} · {source.source_path}</small>{'excerpt' in source && source.excerpt && <p className="source-excerpt">{source.excerpt}</p>}</div></a> })}</div> : <p className="source-empty">Sources for the latest answer will appear here when available.</p>}</section>
      <section className="saved-artifacts"><div className="artifact-section-heading"><h3>Generated Outputs</h3><span>{sessionArtifacts.length}</span></div>{sessionArtifacts.length > 0 ? <div className="artifact-list" aria-label="Generated outputs">{sessionArtifacts.map(artifact => <button key={artifact.id} className={activeArtifact?.id === artifact.id ? 'selected' : ''} onClick={() => { setActiveArtifact(artifact); setArtifactError(''); setArtifactViewerOpen(true) }} title={artifact.title}>{artifact.title}<small>{artifact.artifact_format.toUpperCase()} · {artifact.word_count} words</small></button>)}</div> : <p className="source-empty">Completed essays and documents for this chat will appear here.</p>}</section>
    </aside>
    {(mobileSidebarOpen || mobileArtifactOpen) && <button className="mobile-backdrop" aria-label="Close side panel" onClick={closeMobilePanels} />}
    {artifactViewerOpen && activeArtifact && <div className="artifact-viewer-overlay" onMouseDown={event => { if (event.target === event.currentTarget) setArtifactViewerOpen(false) }}><section className="artifact-viewer-dialog" role="dialog" aria-modal="true" aria-labelledby="artifact-viewer-title"><header className="artifact-viewer-top"><div><span className="eyebrow">ARTIFACT VIEWER · {activeArtifact.artifact_format.toUpperCase()}</span><h2 id="artifact-viewer-title" title={activeArtifact.title}>{activeArtifact.title}</h2></div><div className="artifact-viewer-actions"><button onClick={() => void navigator.clipboard?.writeText(activeArtifact.content)}>Copy</button><a href={`data:text/${activeArtifact.artifact_format === 'html' ? 'html' : 'markdown'};charset=utf-8,${encodeURIComponent(activeArtifact.content)}`} download={`${activeArtifact.title.replace(/[^\w-]+/g, '-').toLowerCase()}.${activeArtifact.artifact_format === 'html' ? 'html' : 'md'}`}>Download</a><button className="artifact-viewer-close" aria-label="Close artifact viewer" onClick={() => setArtifactViewerOpen(false)}>×</button></div></header><div className={`artifact-viewer-content ${activeArtifact.artifact_format === 'html' ? 'html-preview' : ''}`}>{activeArtifact.artifact_format === 'html' ? <iframe title={`Artifact preview: ${activeArtifact.title}`} sandbox="" srcDoc={isolatedDocument(activeArtifact)} /> : <><div className="artifact-document-title">{activeArtifact.title}</div><Markdown className="artifact-markdown" content={activeArtifact.content} /><div className="artifact-source-list"><strong>SOURCES · {activeArtifact.word_count} WORDS</strong>{activeArtifact.sources.map(source => { const url = safeExternalUrl(source.url); return <a key={source.chunk_id} href={url} target={url ? '_blank' : undefined} rel={url ? 'noopener noreferrer' : undefined}>{source.source_id} · {source.title}</a> })}</div></>}</div></section></div>}
    {deleteDialogOpen && <div className="dialog-backdrop"><section className="delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-title" aria-describedby="delete-description"><span className="eyebrow">PERMANENT ACTION</span><h2 id="delete-title">Delete your account?</h2><p id="delete-description">This permanently deletes this account and its chats, messages, and saved artifacts. Shared transcript data is not affected. This cannot be undone.</p><label>Type DELETE to confirm<input autoComplete="off" value={deleteConfirmation} onChange={event => setDeleteConfirmation(event.target.value)} /></label><label>Current password<input type="password" autoComplete="current-password" value={deletePassword} onChange={event => setDeletePassword(event.target.value)} /></label>{settingsError && <div className="error-banner" role="alert">{settingsError}</div>}<div className="dialog-actions"><button className="settings-secondary" disabled={deleteBusy} onClick={() => setDeleteDialogOpen(false)}>Cancel</button><button className="settings-danger" disabled={deleteConfirmation !== 'DELETE' || !deletePassword || deleteBusy} onClick={() => void confirmDeleteAccount()}>{deleteBusy ? 'Deleting…' : 'Delete account'}</button></div></section></div>}
  </main>
}
