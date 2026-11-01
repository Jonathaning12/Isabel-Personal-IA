import { useEffect, useState } from "react";

/** Connect Isabel to the user's Google Calendar and Gmail (read only) with their own OAuth
 * client. The secret goes straight to the main process, which stores it encrypted. */
export function GoogleSettings() {
  const [status, setStatus] = useState<{ connected: boolean; clientId: string } | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void window.assistant?.googleStatus().then((s) => {
      setStatus(s);
      if (s?.clientId) setClientId(s.clientId);
    });
  }, []);

  const connect = async () => {
    setBusy(true);
    setMessage("Se abrió el navegador: inicia sesión en Google y acepta los permisos.");
    const result = await window.assistant!.googleConnect(clientId, clientSecret);
    setBusy(false);
    setClientSecret("");
    setMessage(result.ok ? "¡Conectado! Prueba: «Isabel, ¿qué tengo hoy en el calendario?»." : (result.error ?? "No se pudo conectar."));
    setStatus(await window.assistant!.googleStatus());
  };

  const disconnect = async () => {
    await window.assistant!.googleDisconnect();
    setStatus(await window.assistant!.googleStatus());
    setMessage("Desconectado.");
  };

  return (
    <>
      <p className="hint">
        Con tu calendario Isabel incluye tus citas en los buenos días, te avisa 15 minutos antes y crea eventos (siempre
        con tu aprobación). Con Gmail resume tus correos; solo puede leerlos, nunca enviarlos ni borrarlos.
      </p>
      {status?.connected ? (
        <>
          <p className="hint spotify-ok">● Conectada a Google</p>
          <button type="button" className="button button--ghost button--block" onClick={() => void disconnect()}>
            Desconectar Google
          </button>
        </>
      ) : (
        <>
          <ol className="hint spotify-steps">
            <li>Entra en console.cloud.google.com y crea un proyecto (gratis).</li>
            <li>En «APIs y servicios → Biblioteca», habilita Google Calendar API y Gmail API.</li>
            <li>En «Pantalla de consentimiento de OAuth», tipo Externo, y agrega tu correo como usuario de prueba.</li>
            <li>En «Credenciales → Crear credenciales → ID de cliente de OAuth», elige «App de escritorio».</li>
            <li>Copia el Client ID y el Client Secret aquí.</li>
          </ol>
          <label className="control">
            <span className="control__label">Client ID</span>
            <input
              className="text-input"
              value={clientId}
              onChange={(e) => setClientId(e.target.value.trim())}
              placeholder="….apps.googleusercontent.com"
              spellCheck={false}
            />
          </label>
          <label className="control">
            <span className="control__label">Client Secret</span>
            <input
              className="text-input"
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value.trim())}
              spellCheck={false}
              autoComplete="off"
            />
          </label>
          <button
            type="button"
            className="button button--primary button--block"
            onClick={() => void connect()}
            disabled={busy || !clientId.endsWith(".apps.googleusercontent.com") || clientSecret.length < 10}
          >
            {busy ? "Esperando a Google…" : "Conectar con Google"}
          </button>
        </>
      )}
      {message ? <p className="hint">{message}</p> : null}
    </>
  );
}
