import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";

const root = process.cwd();
const require = createRequire(import.meta.url);
const runtimeModule = require(path.join(root, "runtime", "tasklyric.runtime.js"));
const eventsPath = path.join(root, "fixtures", "sample_events.json");
const fixtureSongDetailPath = path.join(root, "fixtures", "sample_song_detail.json");
const fixtureLyricPath = path.join(root, "fixtures", "sample_lyric.json");
const useLive = process.argv.includes("--live");

function readJson(filePath) {
  const raw = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "");
  return JSON.parse(raw);
}

async function fetchFixture(url, init) {
  if (useLive) {
    const response = await fetch(url, init || {});
    return await response.json();
  }

  if (url.includes("/api/song/detail")) {
    return readJson(fixtureSongDetailPath);
  }
  if (url.includes("/api/song/lyric/v1")) {
    return readJson(fixtureLyricPath);
  }
  throw new Error(`no fixture for url: ${url}`);
}

async function main() {
  const handlers = new Map();
  const configStore = new Map();
  const logs = [];
  const nativeCalls = [];

  const hostApi = {
    registerCall(name, handler) {
      handlers.set(name, handler);
    },
    async callNative(method, payload) {
      nativeCalls.push({ method, payload });
      return 0;
    },
    async fetchJson(url, init) {
      return await fetchFixture(url, init);
    },
    getConfig(key, defaultValue) {
      return configStore.has(key) ? configStore.get(key) : defaultValue;
    },
    setConfig(key, value) {
      configStore.set(key, value);
      return value;
    },
    log(level, message, meta) {
      logs.push({ level, message, meta });
      return 0;
    }
  };

  const runtime = runtimeModule.createRuntime(hostApi);
  runtime.start();

  const events = readJson(eventsPath);
  for (const event of events) {
    const handler = handlers.get(event.name);
    if (!handler) {
      throw new Error(`missing handler for event: ${event.name}`);
    }
    await handler(event.payload);
  }

  console.log(JSON.stringify({
    events,
    logs,
    nativeCalls,
    configStore: Object.fromEntries(configStore.entries()),
    runtimeState: runtime.getState()
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
