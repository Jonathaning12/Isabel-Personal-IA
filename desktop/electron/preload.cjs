// The bridge between the UI and the main process: only these functions exist in the UI.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("assistant", {
  request: (method, route, body) => ipcRenderer.invoke("api:request", { method, route, body }),
  pickAndIngest: () => ipcRenderer.invoke("docs:pick-and-ingest"),
  transcribe: (wavBytes) => ipcRenderer.invoke("voice:transcribe", wavBytes),
  speak: (text, voice) => ipcRenderer.invoke("voice:speak", { text, voice }),
  loadSettings: () => ipcRenderer.invoke("settings:load"),
  saveSettings: (settings) => ipcRenderer.invoke("settings:save", settings),
  windowInfo: () => ipcRenderer.invoke("window:info"),
  wakeModel: () => ipcRenderer.invoke("wake:model"),
  openInObsidian: (vault, file) => ipcRenderer.invoke("obsidian:open", { vault, file }),
  runAction: (tool, args, threadId, toolCallId) =>
    ipcRenderer.invoke("computer:run", { tool, args, threadId, toolCallId }),
  // A reminder is due (fired by the main process, also while the window is in the tray).
  // reminder = { text, at (ms), early (warned minutes before) }
  onReminder: (callback) => {
    const listener = (_event, reminder) => callback(reminder);
    ipcRenderer.on("reminder", listener);
    return () => ipcRenderer.removeListener("reminder", listener);
  },
  // Morning greeting: the main process says when it is time; settings are kept there.
  onMorning: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("morning", listener);
    return () => ipcRenderer.removeListener("morning", listener);
  },
  morningSettings: () => ipcRenderer.invoke("morning:get"),
  setMorning: (value) => ipcRenderer.invoke("morning:set", value),
  // Floating status bar: the UI reports its state; the bar sends back mute / send.
  reportStatus: (status) => ipcRenderer.send("status:update", status),
  onStatusBarCommand: (callback) => {
    const listener = (_event, command) => callback(command);
    ipcRenderer.on("statusbar:command", listener);
    return () => ipcRenderer.removeListener("statusbar:command", listener);
  },
  spotifyStatus: () => ipcRenderer.invoke("spotify:status"),
  spotifyConnect: (clientId) => ipcRenderer.invoke("spotify:connect", clientId),
  spotifyDisconnect: () => ipcRenderer.invoke("spotify:disconnect"),
  windowControl: (action) => ipcRenderer.invoke("window:control", action),
  relaunch: () => ipcRenderer.invoke("app:relaunch"),
});
