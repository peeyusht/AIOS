// Build-time constants for both consoles (vite.config.ts, vite.fleet.config.ts): the release from package.json, the
// commit (GIT_COMMIT when built in a container without .git, else git itself), and when it was built.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as { version: string };

function commit(): string {
  if (process.env.GIT_COMMIT) return process.env.GIT_COMMIT.slice(0, 7);
  try {
    return execFileSync("git", ["rev-parse", "--short=7", "HEAD"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return "";
  }
}

export const buildDefines = {
  __APP_VERSION__: JSON.stringify(version),
  __APP_COMMIT__: JSON.stringify(commit()),
  __BUILT_AT__: JSON.stringify(new Date().toISOString()),
};
