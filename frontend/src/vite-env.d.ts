/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_PROXY_TARGET?: string;
  /** Set to `false` to hide the SVG editor route and Edit button. Default: enabled. */
  readonly VITE_EDITOR_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
