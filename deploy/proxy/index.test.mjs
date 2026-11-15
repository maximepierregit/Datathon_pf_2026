import assert from 'node:assert/strict'
import { test } from 'node:test'
import { makeHandler, parseRequest } from './index.mjs'

const SESSION = 'a'.repeat(40)
const event = (body, { method = 'POST', session = SESSION } = {}) => ({
  requestContext: { http: { method } },
  headers: { 'X-Session-Id': session, 'content-type': 'application/json' },
  body: typeof body === 'string' ? body : JSON.stringify(body),
  isBase64Encoded: false,
})

/** Faux flux de réponse Lambda : garde les morceaux écrits et les métadonnées. */
function fakeStream() {
  const s = { chunks: [], meta: null, ended: false }
  const HttpResponseStream = {
    from(_raw, meta) {
      s.meta = meta
      return { write: (c) => s.chunks.push(Buffer.from(c).toString()), end: () => (s.ended = true) }
    },
  }
  return { s, HttpResponseStream }
}

test('refuse un mode inconnu, une session invalide, un GET et un corps trop gros', () => {
  assert.equal(parseRequest(event({ mode: 'initial' })).status, 400)
  assert.equal(parseRequest(event({ mode: 'monport' }, { session: 'court' })).status, 400)
  assert.equal(parseRequest(event({ mode: 'monport' }, { method: 'GET' })).status, 405)
  assert.equal(parseRequest(event('x'.repeat(70_000))).status, 413)
  assert.equal(parseRequest(event('{pas du json')).status, 400)
  assert.deepEqual(parseRequest(event({ mode: 'monport_chat', message: 'salut' })).session, SESSION)
  assert.equal(parseRequest(event({ mode: 'monport_rebuild' })).error, undefined)
})

test('relaie les morceaux du runtime avec la session AgentCore', async () => {
  const sent = []
  const client = {
    async send(cmd) {
      sent.push(cmd.input)
      return { response: (async function* () { yield Buffer.from('data: {"type":"check"}\n\n'); yield Buffer.from('data: {"type":"done"}\n\n') })() }
    },
  }
  const { s, HttpResponseStream } = fakeStream()
  await makeHandler({ client, arn: 'arn:test', HttpResponseStream })(event({ mode: 'monport_check' }), {})
  assert.equal(s.meta.statusCode, 200)
  assert.equal(s.meta.headers['Content-Type'], 'text/event-stream')
  assert.equal(sent[0].runtimeSessionId, SESSION)
  assert.equal(sent[0].agentRuntimeArn, 'arn:test')
  assert.equal(JSON.parse(sent[0].payload.toString()).mode, 'monport_check')
  assert.deepEqual(s.chunks, ['data: {"type":"check"}\n\n', 'data: {"type":"done"}\n\n'])
  assert.ok(s.ended)
})

test('une erreur en cours de flux devient un événement error puis done', async () => {
  const client = {
    async send() {
      return { response: (async function* () { yield Buffer.from('data: {"type":"check"}\n\n'); throw new Error('coupé') })() }
    },
  }
  const { s, HttpResponseStream } = fakeStream()
  await makeHandler({ client, arn: 'arn:test', HttpResponseStream })(event({ mode: 'monport' }), {})
  assert.match(s.chunks.at(-2), /"type":"error"/)
  assert.match(s.chunks.at(-1), /"type":"done"/)
  assert.ok(s.ended)
})

test('une requête invalide répond en SSE sans appeler le runtime', async () => {
  let called = false
  const client = { async send() { called = true } }
  const { s, HttpResponseStream } = fakeStream()
  await makeHandler({ client, arn: 'arn:test', HttpResponseStream })(event({ mode: 'refine' }), {})
  assert.equal(called, false)
  assert.equal(s.meta.statusCode, 400)
  assert.match(s.chunks[0], /"type":"error"/)
})

test('envoie un battement de cœur pendant un long silence', async () => {
  const client = {
    async send() {
      return { response: (async function* () { await new Promise((r) => setTimeout(r, 60)); yield Buffer.from('data: {"type":"done"}\n\n') })() }
    },
  }
  const { s, HttpResponseStream } = fakeStream()
  await makeHandler({ client, arn: 'arn:test', HttpResponseStream, heartbeatMs: 20 })(event({ mode: 'monport' }), {})
  assert.ok(s.chunks.some((c) => c.startsWith(': ping')))
})
