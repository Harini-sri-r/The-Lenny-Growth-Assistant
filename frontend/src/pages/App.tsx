import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { createSession, createShip30Artifact, getProviderStatus, getUserId, listArtifacts, listMessages, listSessions, sendMessage } from '../services/chat'
import type { Artifact, ChatSession, Message, ProviderStatus } from '../types/chat'
import { safeExternalUrl } from '../utils/safeUrl'
import { Markdown } from '../components/Markdown'

export default function App() {
  const [userId] = useState(getUserId)
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSession, setActiveSession] = useState<ChatSession | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [booting, setBooting] = useState(true)
  const [error, setError] = useState('')
  const [retryMessage, setRetryMessage] = useState('')
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null)
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null)
  const [essayForm, setEssayForm] = useState(false)
  const [essayTopic, setEssayTopic] = useState('')
  const [essayAudience, setEssayAudience] = useState('product managers and startup operators')
  const [essayFormat, setEssayFormat] = useState<'markdown' | 'html'>('markdown')
  const [generatingArtifact, setGeneratingArtifact] = useState(false)
  const [artifactError, setArtifactError] = useState('')
  const [artifactNotice, setArtifactNotice] = useState('')
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [mobileArtifactOpen, setMobileArtifactOpen] = useState(false)
  const conversationRef = useRef<HTMLDivElement>(null)

  const refreshSessions = useCallback(async () => {
    const items = await listSessions(userId)
    setSessions(items)
    return items
  }, [userId])

  const openSession = useCallback(async (session: ChatSession) => {
    setMobileSidebarOpen(false)
    setError('')
    setActiveSession(session)
    setLoadingHistory(true)
    try {
      setMessages(await listMessages(session.id, userId))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load this conversation.')
    } finally {
      setLoadingHistory(false)
    }
  }, [userId])

  const startSession = useCallback(async () => {
    setMobileSidebarOpen(false)
    setError('')
    try {
      const session = await createSession(userId)
      setSessions(current => [session, ...current])
      setActiveSession(session)
      setMessages([])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start a conversation.')
    }
  }, [userId])

  useEffect(() => {
    let cancelled = false
    async function initialize() {
      try {
        const items = await refreshSessions()
        if (cancelled) return
        if (items.length) await openSession(items[0])
        else await startSession()
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Could not connect to the assistant.')
      } finally {
        if (!cancelled) setBooting(false)
      }
    }
    void initialize()
    return () => { cancelled = true }
  }, [refreshSessions, openSession, startSession])

  useEffect(() => {
    void listArtifacts(userId).then(setArtifacts).catch(() => undefined)
  }, [userId])

  useEffect(() => {
    void getProviderStatus().then(setProviderStatus).catch(() => setProviderStatus(null))
  }, [])

  useEffect(() => {
    const conversation = conversationRef.current
    if (conversation) conversation.scrollTop = conversation.scrollHeight
  }, [messages, loading, loadingHistory])

  async function generateEssay(event: FormEvent) {
    event.preventDefault()
    if (!activeSession || !essayTopic.trim() || generatingArtifact) return
    setGeneratingArtifact(true)
    setArtifactError('')
    setArtifactNotice('')
    try {
      const artifact = await createShip30Artifact(userId, activeSession.id, essayTopic, essayAudience, essayFormat)
      setArtifacts(current => [artifact, ...current.filter(item => item.id !== artifact.id)])
      setActiveArtifact(artifact)
      setArtifactNotice('Essay generated and saved to this conversation.')
      setMobileArtifactOpen(true)
      setEssayForm(false)
      setEssayTopic('')
    } catch (reason) {
      setArtifactError(reason instanceof Error ? reason.message : 'The essay could not be generated.')
    } finally {
      setGeneratingArtifact(false)
    }
  }

  function isolatedDocument(artifact: Artifact): string {
    const policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; font-src data:">'
    const html = artifact.content
    return /<head[\s>]/i.test(html)
      ? html.replace(/<head([^>]*)>/i, `<head$1>${policy}`)
      : `<!doctype html><html><head><meta charset="utf-8">${policy}</head><body>${html}</body></html>`
  }

  async function sendContent(content: string) {
    if (!content || !activeSession || loading) return
    setDraft('')
    setError('')
    setRetryMessage('')
    setLoading(true)
    const temporary: Message = {
      id: `pending-${Date.now()}`, session_id: activeSession.id, role: 'user', content,
      sources: [], grounded: null, created_at: new Date().toISOString(),
    }
    setMessages(current => [...current, temporary])
    try {
      const response = await sendMessage(activeSession.id, userId, content)
      setMessages(current => [...current.filter(message => message.id !== temporary.id), response.user_message, response.assistant_message])
      setActiveSession(response.session)
      setSessions(current => [response.session, ...current.filter(item => item.id !== response.session.id)])
    } catch (reason) {
      setMessages(current => current.filter(message => message.id !== temporary.id))
      setDraft(content)
      setRetryMessage(content)
      setError(reason instanceof Error ? reason.message : 'Message could not be sent.')
    } finally {
      setLoading(false)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    await sendContent(draft.trim())
  }

  function closeMobilePanels() {
    setMobileSidebarOpen(false)
    setMobileArtifactOpen(false)
  }

  const showWelcome = messages.length === 0

  return <main className="shell">
    <aside id="conversation-sidebar" className={`sidebar ${mobileSidebarOpen ? 'mobile-panel-open' : ''}`} aria-label="Conversation sidebar">
      <div className="brand"><span className="brand-mark">L</span><div><strong>Lenny</strong><small>GROWTH ASSISTANT</small></div></div>
      <button className="mobile-close" onClick={() => setMobileSidebarOpen(false)} aria-label="Close conversations">×</button>
      <button className="new-chat" onClick={() => void startSession()}><span aria-hidden="true">＋</span> New conversation</button>
      <div className="side-label">CONVERSATIONS</div>
      <nav className="session-list" aria-label="Conversations">
        {sessions.map(session => <button key={session.id} className={`nav session-nav ${activeSession?.id === session.id ? 'active' : ''}`} onClick={() => void openSession(session)} title={session.title}>
          <span aria-hidden="true">◉</span><span>{session.title}</span>
        </button>)}
      </nav>
      <details className="provider-config">
        <summary>Provider configuration</summary>
        {providerStatus ? <>
          <p className="provider-route"><span>Configured route</span><strong>{providerStatus.route_label}</strong></p>
          <div className="provider-list" aria-label="Provider configuration status">
            {providerStatus.providers.filter(provider => ['gemini', 'ollama', 'anthropic'].includes(provider.id)).map(provider => {
              const stateLabels = {
                selected: 'Selected in backend',
                fallback: 'Fallback configured',
                optional: 'Optional · credential set',
                credentials_missing: 'Credentials not set',
                unavailable: 'Not supported by backend',
              }
              return <div className={`provider-row provider-${provider.id}`} key={provider.id}>
                <span className="provider-dot" aria-hidden="true" />
                <span className="provider-name">{provider.label}<small>{provider.model ?? 'No model configured'}</small></span>
                <span className="provider-state">{stateLabels[provider.state]}</span>
              </div>
            })}
          </div>
          <p className="provider-note">{providerStatus.note}</p>
        </> : <p className="provider-note">Provider configuration status is unavailable. No provider is claimed as active.</p>}
      </details>
      <div className="sidebar-bottom"><span className="avatar">L</span><div><strong>Local workspace</strong><small>Conversation history saved</small></div></div>
    </aside>

    <section className={`main ${mobileArtifactOpen ? 'mobile-chat-hidden' : ''}`}>
      <header className="topbar">
        <div className="crumb">Workspace <span>/</span> {activeSession?.title ?? 'Ask Lenny'}</div>
        <div className="header-actions">
          <button className="mobile-action" aria-expanded={mobileSidebarOpen} aria-controls="conversation-sidebar" onClick={() => setMobileSidebarOpen(value => !value)}>Conversations</button>
          <button className="mobile-action" aria-expanded={mobileArtifactOpen} aria-controls="artifact-panel" onClick={() => setMobileArtifactOpen(value => !value)}>Artifacts</button>
          <div className={`status ${loading ? 'status-busy' : ''}`} role="status"><i /> {booting || loadingHistory ? 'Loading…' : loading ? 'Preparing an answer…' : providerStatus ? `Configured · ${providerStatus.route_label}` : 'Provider configuration unavailable'}</div>
        </div>
      </header>

      <div className="conversation" ref={conversationRef} aria-live="polite" aria-busy={loading || loadingHistory}>
        {loadingHistory && <div className="conversation-state">Loading conversation…</div>}
        {!loadingHistory && showWelcome && <div className="welcome">
          <div className="spark">✳</div><div className="eyebrow">LENNY GROWTH ASSISTANT</div>
          <h1>Good ideas start<br />with a better question.</h1>
          <p>Explore advice from Lenny’s podcast and newsletter.<br />Ask about product, growth, teams, and building.</p>
          <div className="suggestions">
            <button onClick={() => setDraft('How do I find product-market fit?')}>↗ <span>Finding product-market fit</span></button>
            <button onClick={() => setDraft('How should I prioritize our roadmap?')}>↗ <span>Prioritizing a roadmap</span></button>
            <button onClick={() => setDraft('How do I build a strong product team?')}>↗ <span>Building great teams</span></button>
          </div>
        </div>}
        {!loadingHistory && !showWelcome && <div className="message-list">
          {messages.map(message => <article key={message.id} className={`message ${message.role}`}>
            <div className="message-label">{message.role === 'user' ? 'YOU' : 'LENNY ASSISTANT'}</div>
            {message.role === 'assistant'
              ? <Markdown className="message-content markdown-content" content={message.content} />
              : <div className="message-content user-content">{message.content}</div>}
            {message.role === 'assistant' && message.sources.length > 0 && <div className="sources">
              <div className="sources-title">SOURCES</div>
              {message.sources.map(source => {
                const url = safeExternalUrl(source.url)
                return <a key={source.chunk_id} href={url} target={url ? '_blank' : undefined} rel={url ? 'noopener noreferrer' : undefined} className="source-card">
                  <span>{source.source_id}</span><div><strong>{source.title}</strong><small>{source.document_type} · {source.source_path}</small></div>{url && <b aria-hidden="true">↗</b>}
                </a>
              })}
            </div>}
            {message.role === 'assistant' && message.grounded === false && <div className="evidence-note">The indexed library did not provide enough relevant evidence for this answer.</div>}
          </article>)}
          {loading && <div className="thinking" role="status"><i /><i /><i /> Searching the library and preparing an answer…</div>}
        </div>}
      </div>

      <div className="composer-wrap">
        {error && <div className="error-banner" role="alert">{error}{retryMessage && <button type="button" disabled={loading} onClick={() => void sendContent(retryMessage)}>Retry message</button>}</div>}
        {essayForm && <form className="essay-form" onSubmit={generateEssay}>
          <label>Essay topic<input value={essayTopic} onChange={event => setEssayTopic(event.target.value)} required minLength={3} maxLength={400} placeholder="What should the essay explore?" /></label>
          <label>Audience<input value={essayAudience} onChange={event => setEssayAudience(event.target.value)} maxLength={300} /></label>
          <label>Format<select value={essayFormat} onChange={event => setEssayFormat(event.target.value as 'markdown' | 'html')}><option value="markdown">Markdown</option><option value="html">HTML + CSS</option></select></label>
          {artifactError && <div className="error-banner artifact-error" role="alert">Essay generation failed: {artifactError}</div>}
          <button type="submit" disabled={generatingArtifact || !activeSession}>{generatingArtifact ? 'Searching sources and writing…' : artifactError ? 'Retry essay generation' : 'Generate grounded essay'}</button>
        </form>}
        {artifactNotice && <div className="success-banner" role="status">{artifactNotice}</div>}
        <form className="composer" onSubmit={submit}>
          <textarea aria-label="Ask a question" placeholder="Ask a question about product or growth…" value={draft} onChange={event => setDraft(event.target.value)} disabled={booting || loading || !activeSession} />
          <div className="composer-footer"><span>Answers use retrieved passages and link to their sources.</span><button aria-label="Send message" disabled={!draft.trim() || loading || !activeSession}>↑</button></div>
        </form>
        <div className="composer-actions"><button className="essay-launch" onClick={() => { setEssayForm(value => !value); setArtifactError('') }} disabled={!activeSession}>✳ Create Ship 30 for 30 essay</button></div>
        <div className="fineprint">Answers may be incomplete. Review the linked source passages.</div>
      </div>
    </section>

    <aside id="artifact-panel" className={`artifact ${mobileArtifactOpen ? 'mobile-panel-open' : ''}`} aria-label="Artifact viewer">
      <div className="artifact-head"><div><span className="eyebrow">YOUR WORKSPACE</span><h2>Artifacts</h2></div><span>{artifacts.length}</span>
        <button className="mobile-close" onClick={() => setMobileArtifactOpen(false)} aria-label="Close artifacts">×</button>
      </div>
      {artifactNotice && <div className="artifact-notice" role="status">{artifactNotice}</div>}
      {artifacts.length > 0 && <div className="artifact-list" aria-label="Saved artifacts">{artifacts.map(artifact => <button key={artifact.id} className={activeArtifact?.id === artifact.id ? 'selected' : ''} onClick={() => { setActiveArtifact(artifact); setArtifactError('') }}>
        {artifact.title}<small>{artifact.artifact_format.toUpperCase()} · {artifact.word_count} words</small>
      </button>)}</div>}
      {artifactError && !essayForm && <div className="error-banner" role="alert">Essay generation failed: {artifactError} <button onClick={() => { setEssayForm(true); setMobileArtifactOpen(false) }}>Review and retry</button></div>}
      {activeArtifact ? <>
        <div className="artifact-document">
          <div className="artifact-document-title">{activeArtifact.title}</div>
          {activeArtifact.artifact_format === 'html'
            ? <iframe title={`Artifact preview: ${activeArtifact.title}`} sandbox="" srcDoc={isolatedDocument(activeArtifact)} />
            : <Markdown className="artifact-markdown" content={activeArtifact.content} />}
          <div className="artifact-source-list"><strong>GROUNDED SOURCES · {activeArtifact.word_count} WORDS</strong>
            {activeArtifact.sources.map(source => {
              const url = safeExternalUrl(source.url)
              return <a key={source.chunk_id} href={url} target={url ? '_blank' : undefined} rel={url ? 'noopener noreferrer' : undefined}>{source.source_id} · {source.title}</a>
            })}
          </div>
        </div>
        <div className="artifact-foot">SANDBOXED ARTIFACT PREVIEW <span>{activeArtifact.artifact_format}</span></div>
      </> : <>
        <div className="artifact-empty"><div className="artifact-icon">✳</div><strong>Artifact viewer</strong><p>Create a Ship 30 for 30 essay to preview a grounded Markdown or HTML artifact.</p></div>
        <div className="artifact-foot">ARTIFACT VIEWER <span>{generatingArtifact ? 'Generating…' : 'Ready'}</span></div>
      </>}
    </aside>
    {(mobileSidebarOpen || mobileArtifactOpen) && <button className="mobile-backdrop" aria-label="Close side panel" onClick={closeMobilePanels} />}
  </main>
}
