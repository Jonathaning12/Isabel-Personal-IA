// Before packaging: records where this project lives, so the installed app can find the
// API token the backend writes in <project>/data/api_token. The file is a build artifact
// (build/ is gitignored) and holds a folder path only, no secret.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const projectDir = resolve(here, "..", "..");
mkdirSync(resolve(here, "..", "build"), { recursive: true });
writeFileSync(resolve(here, "..", "build", "project.json"), JSON.stringify({ projectDir }, null, 2));
console.log(`project folder for the installed app: ${projectDir}`);
