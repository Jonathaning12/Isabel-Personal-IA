// Bridge for the floating status bar: it receives the assistant's state and can send only
// the commands the main process accepts (toggleMic, send, open) plus its own size.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("statusBar", {
  onStatus: (callback) => ipcRenderer.on("status", (_event, status) => callback(status)),
  command: (command) => ipcRenderer.send("statusbar:command", command),
  // mode: "collapsed" (thin strip) | "expanded" (the bar) | "answer" (bar + last answer)
  resize: (mode) => ipcRenderer.send("statusbar:resize", mode),
  onCollapse: (callback) => ipcRenderer.on("collapse", () => callback()),
});
