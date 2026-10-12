// Entry point of the fleet server's console (vite.fleet.config.ts builds it; the server's image serves it).
import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import FleetApp from "./App";
import "../styles.css";

// The theme before the first paint. In a file, not in the page: the server allows no inline script.
try {
  const t = localStorage.getItem("sf-theme");
  if (t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches) document.documentElement.classList.add("dark");
} catch { /* storage refused: light theme */ }

/** A page that throws must not leave a blank window: say what happened and offer a reload. */
class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div role="alert" className="mx-auto mt-24 max-w-xl rounded-lg border bg-card p-6 text-sm">
        <h1 className="text-base font-semibold">This page hit a problem</h1>
        <p className="mt-2 text-muted-foreground">Nothing was changed on the server or on any PC.</p>
        <pre className="mt-3 overflow-auto rounded-md bg-muted p-3 text-xs">{String(error.message || error)}</pre>
        <div className="mt-4 flex gap-2">
          <button className="rounded-md border px-3 py-1.5 font-medium hover:bg-accent" onClick={() => location.reload()}>Reload</button>
          <a className="rounded-md border px-3 py-1.5 font-medium hover:bg-accent" href="#/overview" onClick={() => this.setState({ error: null })}>Back to the overview</a>
        </div>
      </div>
    );
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Boundary>
      <FleetApp />
    </Boundary>
  </StrictMode>,
);
