// Proxy de streaming : Lambda Function URL (RESPONSE_STREAM) → AgentCore Runtime (InvokeAgentRuntime).
// Le navigateur ne peut pas signer en SigV4 ; la Lambda le fait avec son rôle et relaie le flux SSE sans tampon.
// Le CORS (préflight compris) est géré par la Function URL elle-même.
import { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } from '@aws-sdk/client-bedrock-agentcore'

export const MODES = new Set(['monport_check', 'monport', 'monport_chat', 'monport_rebuild'])
export const MAX_BODY = 64 * 1024
export const SESSION_RE = /^[A-Za-z0-9_-]{33,100}$/
const HEARTBEAT_MS = 15_000

const sse = (obj) => `data: ${JSON.stringify(obj)}\n\n`

/** Valide la requête. Retourne { payload, session } ou { error, status }. */
export function parseRequest(event) {
  const method = event?.requestContext?.http?.method
  if (method !== 'POST') return { status: 405, error: 'Méthode non permise.' }
  const headers = Object.fromEntries(Object.entries(event.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]))
  const session = headers['x-session-id'] ?? ''
  if (!SESSION_RE.test(session)) return { status: 400, error: 'En-tête X-Session-Id invalide.' }
  const raw = event.isBase64Encoded ? Buffer.from(event.body ?? '', 'base64') : Buffer.from(event.body ?? '', 'utf8')
  if (raw.length === 0 || raw.length > MAX_BODY) return { status: 413, error: 'Requête vide ou trop volumineuse.' }
  let payload
  try {
    payload = JSON.parse(raw.toString('utf8'))
  } catch {
    return { status: 400, error: 'Le corps doit être du JSON.' }
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) || !MODES.has(payload.mode)) {
    return { status: 400, error: 'Mode inconnu.' }
  }
  return { payload, session }
}

/** Fabrique le gestionnaire ; `client` et `stream` sont injectables pour les tests. */
export function makeHandler({ client, arn, HttpResponseStream, heartbeatMs = HEARTBEAT_MS }) {
  return async (event, responseStream) => {
    const req = parseRequest(event)
    const out = HttpResponseStream.from(responseStream, {
      statusCode: req.error ? req.status : 200,
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no' },
    })
    if (req.error) {
      out.write(sse({ type: 'error', message: req.error }))
      out.write(sse({ type: 'done' }))
      out.end()
      return
    }
    // Commentaire SSE régulier : garde la connexion ouverte (CloudFront coupe une origine muette après 60 s).
    const beat = setInterval(() => out.write(': ping\n\n'), heartbeatMs)
    try {
      const res = await client.send(
        new InvokeAgentRuntimeCommand({
          agentRuntimeArn: arn,
          runtimeSessionId: req.session,
          payload: Buffer.from(JSON.stringify(req.payload)),
          contentType: 'application/json',
          accept: 'text/event-stream',
        }),
      )
      for await (const chunk of res.response) out.write(chunk)
    } catch (err) {
      console.error('Appel du runtime en échec', err?.name, err?.message)
      out.write(sse({ type: 'error', message: 'Mes agents ne répondent pas. Réessaie dans un instant.' }))
      out.write(sse({ type: 'done' }))
    } finally {
      clearInterval(beat)
      out.end()
    }
  }
}

// Dans Lambda, `awslambda` est global ; ailleurs (tests), on n'exporte que les fabriques.
export const handler = typeof globalThis.awslambda?.streamifyResponse === 'function'
  ? globalThis.awslambda.streamifyResponse(
      makeHandler({
        client: new BedrockAgentCoreClient({}),
        arn: process.env.AGENT_RUNTIME_ARN,
        HttpResponseStream: globalThis.awslambda.HttpResponseStream,
      }),
    )
  : undefined
