import { afterEach, describe, expect, it, vi } from 'vitest'
import { createConversationArtifact, createShip30Artifact, getMe, getProviderStatus, listArtifacts, listSessions, register, sendMessage } from './chat'

const apiBase = '/api/v1'

afterEach(() => vi.unstubAllGlobals())

describe('Ship 30 for 30 artifact API', () => {
  it('posts session-scoped Markdown or HTML requests to the dedicated backend endpoint', async () => {
    const result = { id: 'artifact-1', artifact_format: 'html' }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result })
    vi.stubGlobal('fetch', fetchMock)

    await expect(createShip30Artifact('session-1', 'Retention', 'Founders', 'html')).resolves.toEqual(result)

    expect(fetchMock).toHaveBeenCalledWith(`${apiBase}/artifacts/ship30`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ session_id: 'session-1', topic: 'Retention', audience: 'Founders', artifact_format: 'html' }),
    }))
  })

  it('maps backend generation errors to safe frontend guidance instead of returning a preview result', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'Insufficient evidence' }) })
    vi.stubGlobal('fetch', fetchMock)

    await expect(createShip30Artifact('session-1', 'Retention', 'Founders', 'markdown')).rejects.toThrow('This request could not be completed. Please check the details and try again.')
  })

  it('posts a format-selected artifact request based on the current conversation', async () => {
    const result = { id: 'artifact-2', artifact_format: 'html' }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 201, json: async () => result })
    vi.stubGlobal('fetch', fetchMock)

    await expect(createConversationArtifact('session-1', 'Summarize our retention discussion', 'html')).resolves.toEqual(result)

    expect(fetchMock).toHaveBeenCalledWith(`${apiBase}/artifacts/from-chat`, expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ session_id: 'session-1', request: 'Summarize our retention discussion', artifact_format: 'html' }),
    }))
  })
})

describe('provider configuration API', () => {
  it('reads the secret-free backend provider route', async () => {
    const result = { configured_route: 'ollama', route_label: 'Ollama local provider', providers: [] }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getProviderStatus()).resolves.toEqual(result)
    expect(fetchMock).toHaveBeenCalledWith(`${apiBase}/providers`, expect.any(Object))
  })
})

describe('session and artifact history API routes', () => {
  it('registers through the public auth contract without requiring a session', async () => {
    const result = { id: 'user-1', email: 'person@example.test', display_name: 'Person' }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 201, headers: { get: () => 'csrf-value' }, json: async () => result })
    vi.stubGlobal('fetch', fetchMock)

    await expect(register('person@example.test', 'a secure password', 'Person')).resolves.toEqual(result)
    expect(fetchMock).toHaveBeenCalledWith(`${apiBase}/auth/register`, expect.objectContaining({
      method: 'POST', credentials: 'include',
      body: JSON.stringify({ email: 'person@example.test', password: 'a secure password', display_name: 'Person' }),
    }))
  })

  it('restores the auth session through the same browser hostname with cookies included', async () => {
    const result = { id: 'user-1', email: 'person@example.test', display_name: 'Person' }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, headers: { get: () => null }, json: async () => result })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getMe()).resolves.toEqual(result)
    expect(fetchMock).toHaveBeenCalledWith(`${apiBase}/auth/me`, expect.objectContaining({ credentials: 'include' }))
  })

  it('deduplicates concurrent auth bootstrap checks into one /me request', async () => {
    const result = { id: 'user-1', email: 'person@example.test', display_name: 'Person' }
    let resolveResponse!: (value: Response) => void
    const fetchMock = vi.fn(() => new Promise<Response>(resolve => { resolveResponse = resolve }))
    vi.stubGlobal('fetch', fetchMock)

    const first = getMe()
    const second = getMe()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    resolveResponse(new Response(JSON.stringify(result), { status: 200 }))
    await expect(Promise.all([first, second])).resolves.toEqual([result, result])
  })

  it('turns backend field validation arrays into readable errors', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 422,
      json: async () => ({ detail: [{ loc: ['body', 'password'], msg: 'String should have at least 12 characters' }] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(register('person@example.test', 'short', 'Person'))
      .rejects.toThrow('password: String should have at least 12 characters')
  })

  it('does not expose internal server error details to the frontend', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 500,
      json: async () => ({ detail: 'SQL password=private-secret at C:\\server\\db.py' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(getMe()).rejects.toMatchObject({ message: 'The service is temporarily unavailable. Please try again.', status: 500 })
  })

  it('does not mislabel an anonymous protected-route 401 as invalid login credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: 'Unknown proxy response' }) })
    vi.stubGlobal('fetch', fetchMock)
    await expect(listSessions()).rejects.toMatchObject({ message: 'Sign in to continue', status: 401 })
  })

  it('uses cookie credentials and a stable message request id for chat posts', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    await sendMessage('session-1', 'Question', 'stable-client-key')
    expect(fetchMock).toHaveBeenCalledWith(`${apiBase}/chat/sessions/session-1/messages`, expect.objectContaining({
      credentials: 'include', method: 'POST', body: JSON.stringify({ message: 'Question', client_message_id: 'stable-client-key' }),
    }))
  })

  it('loads conversation history through the versioned chat route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] })
    vi.stubGlobal('fetch', fetchMock)

    await expect(listSessions()).resolves.toEqual([])

    expect(fetchMock).toHaveBeenCalledWith(`${apiBase}/chat/sessions`, expect.any(Object))
  })

  it('loads artifact history through the versioned artifacts route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] })
    vi.stubGlobal('fetch', fetchMock)

    await expect(listArtifacts()).resolves.toEqual([])

    expect(fetchMock).toHaveBeenCalledWith(`${apiBase}/artifacts`, expect.any(Object))
  })
})
