# AI Studio preview reference

This isolated example demonstrates the browser-to-server shape supplied in the reference HTML. It
is intentionally **not** a Talk2Data UI design and does not connect to Talk2Data data or APIs.

The default model is a deterministic local preview, so no API key is required. The browser sends
only a prompt to the localhost server; the response explicitly says that no external request was
made. The server binds to `127.0.0.1`, accepts exact localhost origins, limits request and response
bytes, bounds rate and concurrent work, enforces a total deadline, rejects absolute/malformed
targets, and cancels when the client disconnects.

```bash
cd examples/canvas/ai-studio
npm test
npm start
```

Open `http://127.0.0.1:4178`. Do not expose this development server to the public internet. A future
real provider adapter must keep credentials server-side and add provider-specific privacy, budget,
logging, cancellation, and abuse controls.
