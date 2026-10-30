// Downloads the small Spanish Vosk model (Apache-2.0, ~40 MB) used to detect the wake word
// "Isabel" locally, and repackages it as the .tar.gz that vosk-browser loads.
// Usage: npm run fetch-model   (needs the `tar` command: built into Windows 10+, macOS, Linux)

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const NAME = "vosk-model-small-es-0.42";
const URL = `https://alphacephei.com/vosk/models/${NAME}.zip`;
const root = join(dirname(fileURLToPath(import.meta.url)), "..", "models");
const target = join(root, `${NAME}.tar.gz`);

if (existsSync(target)) {
  console.log(`Ya está descargado: ${target}`);
  process.exit(0);
}

mkdirSync(root, { recursive: true });
const zip = join(root, `${NAME}.zip`);
console.log(`Descargando ${URL} …`);
const response = await fetch(URL);
if (!response.ok) throw new Error(`Descarga fallida: HTTP ${response.status}`);
writeFileSync(zip, Buffer.from(await response.arrayBuffer()));

console.log("Preparando el modelo…");
const work = join(root, "tmp");
rmSync(work, { recursive: true, force: true });
mkdirSync(work);
try {
  execFileSync("tar", ["-xf", zip, "-C", work]); // bsdtar (Windows/macOS) reads .zip
} catch {
  execFileSync("unzip", ["-q", zip, "-d", work]); // GNU tar cannot: fall back to unzip
}
execFileSync("tar", ["-czf", target, "-C", work, NAME]);
rmSync(work, { recursive: true, force: true });
rmSync(zip, { force: true });
console.log(`Listo: ${target}`);
