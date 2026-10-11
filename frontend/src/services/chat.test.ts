import { afterEach, describe, expect, it, vi } from 'vitest'
import { createShip30Artifact, getProviderStatus, listArtifacts, listSessions } from './chat'

afterEach(() => vi.unstubAllGlobals())

describe('Ship 30 for 30 artifact API', () => {
  it('posts session-scoped Markdown or HTML requests to the dedicated backend endpoint', async () => {
    const result = { id: 'artifact-1', artifact_format: 'html' }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result })
    vi.stubGlobal('fetch', fetchMock)

    await expect(createShip30Artifact('user-1', 'session-1', 'Retention', 'Founders', 'html')).resolves.toEqual(result)

    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/api/v1/artifacts/ship30', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ user_id: 'user-1', session_id: 'session-1', topic: 'Retention', audience: 'Founders', artifact_format: 'html' }),
    }))
  })

  it('surfaces backend generation errors instead of returning a preview result', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'Insufficient evidence' }) })
    vi.stubGlobal('fetch', fetchMock)

    await expect(createShip30Artifact('user-1', 'session-1', 'Retention', 'Founders', 'markdown')).rejects.toThrow('Insufficient evidence')
  })
})

describe('provider configuration API', () => {
  it('reads the secret-free backend provider route', async () => {
    const result = { configured_route: 'ollama', route_label: 'Ollama local provider', providers: [] }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getProviderStatus()).resolves.toEqual(result)
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/api/v1/providers', expect.any(Object))
  })
})

describe('session and artifact history API routes', () => {
  it('loads conversation history through the versioned chat route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] })
    vi.stubGlobal('fetch', fetchMock)

    await expect(listSessions('user-1')).resolves.toEqual([])

    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/api/v1/chat/sessions?user_id=user-1', expect.any(Object))
  })

  it('loads artifact history through the versioned artifacts route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] })
    vi.stubGlobal('fetch', fetchMock)

    await expect(listArtifacts('user-1')).resolves.toEqual([])

    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/api/v1/artifacts?user_id=user-1', expect.any(Object))
  })
})
