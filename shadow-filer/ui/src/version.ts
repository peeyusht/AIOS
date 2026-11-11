/* Which release and which build this console is: set at build time by vite.config.ts and vite.fleet.config.ts
   from package.json's "version", the git commit (or GIT_COMMIT when built in a container) and the build time. */
declare const __APP_VERSION__: string;
declare const __APP_COMMIT__: string;
declare const __BUILT_AT__: string;

export const APP = {
  version: __APP_VERSION__,
  commit: __APP_COMMIT__,
  builtAt: __BUILT_AT__,
  label: `v${__APP_VERSION__}${__APP_COMMIT__ ? ` · ${__APP_COMMIT__}` : ""}`,
};
