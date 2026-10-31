// Floating status bar. It rests as a thin strip at the top of the screen (its color shows
// the state) and opens into the full bar when the mouse comes near. It only shows the
// state the main window reports and sends three commands back (mute the mic, send a typed
// message, open the app). It cannot approve anything: approvals need the main window.

const LABELS = {
  idle: "En espera",
  gathering: "Recopilando información",
  thinking: "Pensando",
  speaking: "Hablando",
  listening: "Escuchando",
  transcribing: "Transcribiendo",
  awaiting: "Necesita tu aprobación · ábrela",
  error: "Algo salió mal",
};
const ANSWER_MS = 9000;
const CLOSE_DELAY_MS = 700; // so the bar does not flicker when the mouse brushes past
const BAR_ANSWER_WINDOW_MS = 120_000; // answers pop up only for messages sent from the bar

const root = document.body;
const bar = document.getElementById("bar");
const label = document.getElementById("label");
const write = document.getElementById("write");
const input = document.getElementById("text");
const answer = document.getElementById("answer");
let lastAnswerId = null;
let sentFromBarAt = 0;
let answerTimer;
let closeTimer;
let hovering = false;

function setMode(mode) {
  root.dataset.mode = mode;
  window.statusBar.resize(mode);
}

const writing = () => !write.hidden;

function collapseSoon() {
  window.clearTimeout(closeTimer);
  closeTimer = window.setTimeout(() => {
    if (!hovering && !writing() && answer.hidden) setMode("collapsed");
  }, CLOSE_DELAY_MS);
}

function showAnswer(text) {
  window.clearTimeout(answerTimer);
  answer.textContent = text ?? "";
  answer.hidden = !text;
  if (text) {
    setMode("answer");
    answerTimer = window.setTimeout(() => showAnswer(null), ANSWER_MS);
  } else if (root.dataset.mode === "answer") {
    setMode(hovering || writing() ? "expanded" : "collapsed");
  }
}

// Collapsed, the window lets clicks through and only opens when the mouse touches the
// strip itself (the top few pixels around it), not the empty space below.
const STRIP_REACH_PX = 14;
root.addEventListener("mousemove", (event) => {
  hovering = true;
  window.clearTimeout(closeTimer);
  if (root.dataset.mode !== "collapsed") return;
  const nearStrip = event.clientY <= STRIP_REACH_PX && Math.abs(event.clientX - window.innerWidth / 2) <= 80;
  if (nearStrip) setMode("expanded");
});
root.addEventListener("mouseleave", () => {
  hovering = false;
  collapseSoon();
});

window.statusBar.onCollapse(() => {
  closeWrite();
  showAnswer(null);
  root.dataset.mode = "collapsed";
});

window.statusBar.onStatus((status) => {
  const phase = Object.hasOwn(LABELS, status.phase) ? status.phase : "idle";
  root.dataset.phase = phase;
  root.dataset.mic = status.micOn ? "on" : "off";
  root.dataset.wake = status.wakeReady ? "ready" : "off";
  let text = LABELS[phase];
  if (phase === "idle") text = !status.micOn ? "Micrófono silenciado" : status.wakeReady ? "Di «Isabel»" : "En espera";
  label.textContent = text;
  document.getElementById("mic").title = status.micOn ? "Silenciar micrófono" : "Activar micrófono";
  // The answer to a message typed in the bar is shown for a moment.
  const id = status.answerId ?? "";
  const fromBar = Date.now() - sentFromBarAt < BAR_ANSWER_WINDOW_MS;
  if (lastAnswerId !== null && id && id !== lastAnswerId && fromBar) showAnswer(status.answer);
  lastAnswerId = id;
});

function openWrite() {
  write.hidden = false;
  bar.dataset.writing = "yes";
  input.focus();
}

function closeWrite() {
  input.value = "";
  write.hidden = true;
  bar.dataset.writing = "no";
}

document.getElementById("mic").addEventListener("click", () => window.statusBar.command({ type: "toggleMic" }));
document.getElementById("open").addEventListener("click", () => window.statusBar.command({ type: "open" }));
document.getElementById("type").addEventListener("click", openWrite);

write.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (text) {
    sentFromBarAt = Date.now();
    window.statusBar.command({ type: "send", text });
  }
  closeWrite();
  collapseSoon();
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeWrite();
    collapseSoon();
  }
});
input.addEventListener("blur", () => {
  if (!input.value.trim()) {
    closeWrite();
    collapseSoon();
  }
});
